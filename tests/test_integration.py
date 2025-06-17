import os
import asyncio
import json
import base64
from datetime import datetime, timedelta, timezone
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
    pytest.fail("MICROSOFT_MCP_CLIENT_ID environment variable is required")


def parse_result(result, tool_name=None):
    """Helper to parse MCP tool results consistently"""
    if result.content and hasattr(result.content[0], "text"):
        text = result.content[0].text
        if text == "[]":
            return []
        data = json.loads(text)
        # FastMCP seems to unwrap single-element lists, so rewrap for consistency
        list_tools = {
            "list_accounts",
            "list_emails",
            "list_events",
            "list_contacts",
            "list_files",
        }
        if tool_name in list_tools and isinstance(data, dict):
            return [data]
        return data
    return []


async def get_session():
    """Get MCP session"""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "microsoft-mcp"],
        env={
            "MICROSOFT_MCP_CLIENT_ID": os.getenv("MICROSOFT_MCP_CLIENT_ID", ""),
            "MICROSOFT_MCP_TENANT_ID": os.getenv("MICROSOFT_MCP_TENANT_ID", "common"),
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def get_account_info(session):
    """Get account info"""
    result = await session.call_tool("list_accounts", {})
    assert not result.isError
    accounts = parse_result(result, "list_accounts")
    assert accounts and len(accounts) > 0, (
        "No accounts found - please authenticate first"
    )

    return {"email": accounts[0]["username"], "account_id": accounts[0]["account_id"]}


@pytest.mark.asyncio
async def test_list_accounts():
    """Test list_accounts tool"""
    async for session in get_session():
        result = await session.call_tool("list_accounts", {})
        assert not result.isError
        accounts = parse_result(result, "list_accounts")
        assert accounts is not None
        assert len(accounts) > 0
        assert "username" in accounts[0]
        assert "account_id" in accounts[0]


@pytest.mark.asyncio
async def test_list_emails():
    """Test list_emails tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "list_emails",
            {
                "account_id": account_info["account_id"],
                "limit": 3,
                "include_body": True,
            },
        )
        assert not result.isError
        emails = parse_result(result, "list_emails")
        assert emails is not None
        if len(emails) > 0:
            assert "id" in emails[0]
            assert "subject" in emails[0]
            assert "body" in emails[0]


@pytest.mark.asyncio
async def test_list_emails_without_body():
    """Test list_emails tool without body"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "list_emails",
            {
                "account_id": account_info["account_id"],
                "limit": 3,
                "include_body": False,
            },
        )
        assert not result.isError
        emails = parse_result(result, "list_emails")
        assert emails is not None
        if len(emails) > 0:
            assert "body" not in emails[0]


@pytest.mark.asyncio
async def test_get_email():
    """Test get_email tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_emails", {"account_id": account_info["account_id"], "limit": 1}
        )
        emails = parse_result(list_result, "list_emails")

        if emails and len(emails) > 0:
            email_id = emails[0]["id"]
            result = await session.call_tool(
                "get_email",
                {"email_id": email_id, "account_id": account_info["account_id"]},
            )
            assert not result.isError
            email_detail = parse_result(result)
            assert email_detail is not None
            assert "id" in email_detail
            assert email_detail["id"] == email_id


@pytest.mark.asyncio
async def test_create_email_send_immediately():
    """Test create_email tool with immediate send"""
    async for session in get_session():
        account_info = await get_account_info(session)
        test_attachment = {
            "name": "test.txt",
            "content_base64": base64.b64encode(b"Test attachment content").decode(),
        }

        result = await session.call_tool(
            "create_email",
            {
                "account_id": account_info["account_id"],
                "to": account_info["email"],
                "subject": f"MCP Test - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "body": "Test email with attachment from Microsoft MCP integration tests.",
                "cc": [account_info["email"]],
                "attachments": [test_attachment],
                "send_immediately": True,
            },
        )
        assert not result.isError
        send_result = parse_result(result)
        assert send_result is not None
        assert send_result.get("status") == "sent"


@pytest.mark.asyncio
async def test_create_email_draft():
    """Test create_email tool as draft"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "create_email",
            {
                "account_id": account_info["account_id"],
                "to": account_info["email"],
                "subject": "MCP Test Draft",
                "body": "This is a test draft email",
                "send_immediately": False,
            },
        )
        assert not result.isError
        draft_data = parse_result(result)
        assert draft_data is not None
        assert "id" in draft_data

        draft_id = draft_data["id"]
        delete_result = await session.call_tool(
            "delete_email",
            {"email_id": draft_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_update_email():
    """Test update_email tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_emails", {"account_id": account_info["account_id"], "limit": 1}
        )
        emails = parse_result(list_result, "list_emails")

        if emails and len(emails) > 0:
            email_id = emails[0]["id"]
            original_read_state = emails[0].get("isRead", True)

            result = await session.call_tool(
                "update_email",
                {
                    "email_id": email_id,
                    "account_id": account_info["account_id"],
                    "updates": {"isRead": not original_read_state},
                },
            )
            assert not result.isError

            restore_result = await session.call_tool(
                "update_email",
                {
                    "email_id": email_id,
                    "account_id": account_info["account_id"],
                    "updates": {"isRead": original_read_state},
                },
            )
            assert not restore_result.isError


@pytest.mark.asyncio
async def test_delete_email():
    """Test delete_email tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        draft_result = await session.call_tool(
            "create_email",
            {
                "account_id": account_info["account_id"],
                "to": account_info["email"],
                "subject": "MCP Test Delete",
                "body": "This email will be deleted",
                "send_immediately": False,
            },
        )
        draft_data = parse_result(draft_result)
        if draft_data and "id" in draft_data:
            result = await session.call_tool(
                "delete_email",
                {
                    "email_id": draft_data["id"],
                    "account_id": account_info["account_id"],
                },
            )
            assert not result.isError
            delete_result = parse_result(result)
            assert delete_result is not None
            assert delete_result.get("status") == "deleted"


@pytest.mark.asyncio
async def test_move_email():
    """Test move_email tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_emails",
            {"account_id": account_info["account_id"], "folder": "inbox", "limit": 1},
        )
        emails = parse_result(list_result, "list_emails")

        if emails and len(emails) > 0:
            email_id = emails[0]["id"]
            result = await session.call_tool(
                "move_email",
                {
                    "email_id": email_id,
                    "account_id": account_info["account_id"],
                    "destination_folder": "archive",
                },
            )
            assert not result.isError

            move_result = parse_result(result, "move_email")
            new_email_id = move_result.get("new_id", email_id)

            restore_result = await session.call_tool(
                "move_email",
                {
                    "email_id": new_email_id,
                    "account_id": account_info["account_id"],
                    "destination_folder": "inbox",
                },
            )
            assert not restore_result.isError


@pytest.mark.asyncio
async def test_reply_email():
    """Test reply_email tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        await asyncio.sleep(2)
        list_result = await session.call_tool(
            "list_emails", {"account_id": account_info["account_id"], "limit": 5}
        )
        emails = parse_result(list_result, "list_emails")

        test_email = None
        if emails:
            test_email = next(
                (e for e in emails if "MCP Test" in e.get("subject", "")),
                emails[0] if emails else None,
            )

        if test_email:
            result = await session.call_tool(
                "reply_email",
                {
                    "account_id": account_info["account_id"],
                    "email_id": test_email["id"],
                    "body": "This is a test reply",
                    "reply_all": False,
                },
            )
            assert not result.isError
            reply_result = parse_result(result)
            assert reply_result is not None
            assert reply_result.get("status") == "sent"


@pytest.mark.asyncio
async def test_list_events():
    """Test list_events tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "list_events",
            {
                "account_id": account_info["account_id"],
                "days_ahead": 14,
                "include_details": True,
            },
        )
        assert not result.isError
        events = parse_result(result, "list_events")
        assert events is not None
        if len(events) > 0:
            assert "id" in events[0]
            assert "subject" in events[0]
            assert "start" in events[0]
            assert "end" in events[0]


@pytest.mark.asyncio
async def test_get_event():
    """Test get_event tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_events", {"account_id": account_info["account_id"], "days_ahead": 30}
        )
        events = parse_result(list_result, "list_events")

        if events and len(events) > 0:
            event_id = events[0]["id"]
            result = await session.call_tool(
                "get_event",
                {"event_id": event_id, "account_id": account_info["account_id"]},
            )
            assert not result.isError
            event_detail = parse_result(result)
            assert event_detail is not None
            assert "id" in event_detail
            assert event_detail["id"] == event_id


@pytest.mark.asyncio
async def test_create_event():
    """Test create_event tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        start_time = datetime.now(timezone.utc) + timedelta(days=7)
        end_time = start_time + timedelta(hours=1)

        result = await session.call_tool(
            "create_event",
            {
                "account_id": account_info["account_id"],
                "subject": "MCP Integration Test Event",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "location": "Virtual Meeting Room",
                "body": "This is a test event created by integration tests",
                "attendees": [account_info["email"]],
            },
        )
        assert not result.isError
        event_data = parse_result(result)
        assert event_data is not None
        assert "id" in event_data

        event_id = event_data["id"]
        delete_result = await session.call_tool(
            "delete_event",
            {
                "account_id": account_info["account_id"],
                "event_id": event_id,
                "send_cancellation": False,
            },
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_update_event():
    """Test update_event tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        start_time = datetime.now(timezone.utc) + timedelta(days=8)
        end_time = start_time + timedelta(hours=1)

        create_result = await session.call_tool(
            "create_event",
            {
                "account_id": account_info["account_id"],
                "subject": "MCP Test Event for Update",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
        )
        event_data = parse_result(create_result)
        assert event_data is not None
        event_id = event_data["id"]

        new_start = start_time + timedelta(hours=2)
        new_end = new_start + timedelta(hours=1)

        result = await session.call_tool(
            "update_event",
            {
                "event_id": event_id,
                "account_id": account_info["account_id"],
                "updates": {
                    "subject": "MCP Test Event (Updated)",
                    "start": new_start.isoformat(),
                    "end": new_end.isoformat(),
                    "location": "Conference Room B",
                },
            },
        )
        assert not result.isError

        delete_result = await session.call_tool(
            "delete_event",
            {
                "account_id": account_info["account_id"],
                "event_id": event_id,
                "send_cancellation": False,
            },
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_delete_event():
    """Test delete_event tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        start_time = datetime.now(timezone.utc) + timedelta(days=9)
        end_time = start_time + timedelta(hours=1)

        create_result = await session.call_tool(
            "create_event",
            {
                "account_id": account_info["account_id"],
                "subject": "MCP Test Event for Deletion",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
        )
        event_data = parse_result(create_result)
        assert event_data is not None
        event_id = event_data["id"]

        result = await session.call_tool(
            "delete_event",
            {
                "account_id": account_info["account_id"],
                "event_id": event_id,
                "send_cancellation": False,
            },
        )
        assert not result.isError
        delete_result = parse_result(result)
        assert delete_result is not None
        assert delete_result.get("status") == "deleted"


@pytest.mark.asyncio
async def test_respond_event():
    """Test respond_event tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_events", {"account_id": account_info["account_id"], "days_ahead": 30}
        )
        events = parse_result(list_result, "list_events")

        if events:
            invite_event = next(
                (e for e in events if e.get("attendees") and len(e["attendees"]) > 1),
                None,
            )
            if invite_event:
                result = await session.call_tool(
                    "respond_event",
                    {
                        "account_id": account_info["account_id"],
                        "event_id": invite_event["id"],
                        "response": "tentativelyAccept",
                        "message": "I might be able to attend",
                    },
                )
                if not result.isError:
                    response_result = parse_result(result)
                    assert response_result is not None
                    assert response_result.get("status") == "tentativelyAccept"


@pytest.mark.asyncio
async def test_check_availability():
    """Test check_availability tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        check_start = (
            (datetime.now(timezone.utc) + timedelta(days=1))
            .replace(hour=10, minute=0)
            .isoformat()
        )
        check_end = (
            (datetime.now(timezone.utc) + timedelta(days=1))
            .replace(hour=17, minute=0)
            .isoformat()
        )

        result = await session.call_tool(
            "check_availability",
            {
                "account_id": account_info["account_id"],
                "start": check_start,
                "end": check_end,
                "attendees": [account_info["email"]],
            },
        )
        assert not result.isError
        availability = parse_result(result)
        assert availability is not None


@pytest.mark.asyncio
async def test_list_contacts():
    """Test list_contacts tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "list_contacts", {"account_id": account_info["account_id"], "limit": 10}
        )
        assert not result.isError
        contacts = parse_result(result, "list_contacts")
        assert contacts is not None
        if len(contacts) > 0:
            assert "id" in contacts[0]


@pytest.mark.asyncio
async def test_get_contact():
    """Test get_contact tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_contacts", {"account_id": account_info["account_id"], "limit": 1}
        )
        assert not list_result.isError
        contacts = parse_result(list_result, "list_contacts")
        if contacts and len(contacts) > 0:
            contact_id = contacts[0]["id"]
            result = await session.call_tool(
                "get_contact",
                {"contact_id": contact_id, "account_id": account_info["account_id"]},
            )
            assert not result.isError
            contact_detail = parse_result(result)
            assert contact_detail is not None
            assert "id" in contact_detail


@pytest.mark.asyncio
async def test_create_contact():
    """Test create_contact tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "create_contact",
            {
                "account_id": account_info["account_id"],
                "given_name": "MCP",
                "surname": "TestContact",
                "email_addresses": ["mcp.test@example.com"],
                "phone_numbers": {"mobile": "+1234567890"},
            },
        )
        assert not result.isError
        new_contact = parse_result(result)
        assert new_contact is not None
        assert "id" in new_contact

        contact_id = new_contact["id"]
        delete_result = await session.call_tool(
            "delete_contact",
            {"contact_id": contact_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_update_contact():
    """Test update_contact tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        create_result = await session.call_tool(
            "create_contact",
            {
                "account_id": account_info["account_id"],
                "given_name": "MCPUpdate",
                "surname": "Test",
            },
        )
        assert not create_result.isError
        new_contact = parse_result(create_result)
        contact_id = new_contact["id"]

        result = await session.call_tool(
            "update_contact",
            {
                "contact_id": contact_id,
                "account_id": account_info["account_id"],
                "updates": {"givenName": "MCPUpdated"},
            },
        )
        assert not result.isError

        delete_result = await session.call_tool(
            "delete_contact",
            {"contact_id": contact_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_delete_contact():
    """Test delete_contact tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        create_result = await session.call_tool(
            "create_contact",
            {
                "account_id": account_info["account_id"],
                "given_name": "MCPDelete",
                "surname": "Test",
            },
        )
        assert not create_result.isError
        new_contact = parse_result(create_result)
        contact_id = new_contact["id"]

        result = await session.call_tool(
            "delete_contact",
            {"contact_id": contact_id, "account_id": account_info["account_id"]},
        )
        assert not result.isError
        delete_result = parse_result(result)
        assert delete_result is not None
        assert delete_result.get("status") == "deleted"


@pytest.mark.asyncio
async def test_list_files():
    """Test list_files tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "list_files", {"account_id": account_info["account_id"]}
        )
        assert not result.isError
        files = parse_result(result)
        assert files is not None
        if len(files) > 0:
            assert "id" in files[0]
            assert "name" in files[0]
            assert "type" in files[0]


@pytest.mark.asyncio
async def test_get_file():
    """Test get_file tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        test_content = "Test file content"
        content_b64 = base64.b64encode(test_content.encode()).decode()
        test_filename = f"mcp-test-get-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"

        create_result = await session.call_tool(
            "create_file",
            {
                "account_id": account_info["account_id"],
                "path": test_filename,
                "content_base64": content_b64,
            },
        )
        file_data = parse_result(create_result)
        file_id = file_data["id"]

        result = await session.call_tool(
            "get_file", {"file_id": file_id, "account_id": account_info["account_id"]}
        )
        assert not result.isError
        retrieved_file = parse_result(result)
        assert retrieved_file is not None
        assert "metadata" in retrieved_file
        assert "content_base64" in retrieved_file

        downloaded_content = base64.b64decode(retrieved_file["content_base64"]).decode()
        assert downloaded_content == test_content

        delete_result = await session.call_tool(
            "delete_file",
            {"file_id": file_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_create_file():
    """Test create_file tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        test_content = f"MCP Integration Test\nTimestamp: {datetime.now().isoformat()}"
        content_b64 = base64.b64encode(test_content.encode()).decode()
        test_filename = (
            f"mcp-test-create-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        )

        result = await session.call_tool(
            "create_file",
            {
                "account_id": account_info["account_id"],
                "path": test_filename,
                "content_base64": content_b64,
            },
        )
        assert not result.isError
        upload_result = parse_result(result)
        assert upload_result is not None
        assert "id" in upload_result

        file_id = upload_result["id"]
        delete_result = await session.call_tool(
            "delete_file",
            {"file_id": file_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_update_file():
    """Test update_file tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        test_content = "Original content"
        content_b64 = base64.b64encode(test_content.encode()).decode()
        test_filename = (
            f"mcp-test-update-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        )

        create_result = await session.call_tool(
            "create_file",
            {
                "account_id": account_info["account_id"],
                "path": test_filename,
                "content_base64": content_b64,
            },
        )
        file_data = parse_result(create_result)
        file_id = file_data["id"]

        updated_content = f"Updated content at {datetime.now().isoformat()}"
        updated_b64 = base64.b64encode(updated_content.encode()).decode()

        result = await session.call_tool(
            "update_file",
            {
                "account_id": account_info["account_id"],
                "file_id": file_id,
                "content_base64": updated_b64,
            },
        )
        assert not result.isError

        delete_result = await session.call_tool(
            "delete_file",
            {"file_id": file_id, "account_id": account_info["account_id"]},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_delete_file():
    """Test delete_file tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        test_content = "File to be deleted"
        content_b64 = base64.b64encode(test_content.encode()).decode()
        test_filename = (
            f"mcp-test-delete-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        )

        create_result = await session.call_tool(
            "create_file",
            {
                "account_id": account_info["account_id"],
                "path": test_filename,
                "content_base64": content_b64,
            },
        )
        file_data = parse_result(create_result)
        file_id = file_data["id"]

        result = await session.call_tool(
            "delete_file",
            {"file_id": file_id, "account_id": account_info["account_id"]},
        )
        assert not result.isError
        delete_result = parse_result(result)
        assert delete_result is not None
        assert delete_result.get("status") == "deleted"


@pytest.mark.asyncio
async def test_get_attachment():
    """Test get_attachment tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        list_result = await session.call_tool(
            "list_emails", {"account_id": account_info["account_id"], "limit": 20}
        )
        emails = parse_result(list_result, "list_emails")

        emails_with_attachments = [e for e in emails if e.get("hasAttachments")]
        if emails_with_attachments:
            email_with_attach = emails_with_attachments[0]
            email_result = await session.call_tool(
                "get_email",
                {
                    "email_id": email_with_attach["id"],
                    "account_id": account_info["account_id"],
                },
            )
            email_detail = parse_result(email_result)

            if (
                email_detail
                and "attachments" in email_detail
                and email_detail["attachments"]
            ):
                attachment = email_detail["attachments"][0]
                result = await session.call_tool(
                    "get_attachment",
                    {
                        "email_id": email_with_attach["id"],
                        "account_id": account_info["account_id"],
                        "attachment_id": attachment["id"],
                    },
                )
                assert not result.isError
                attachment_data = parse_result(result)
                assert attachment_data is not None
                assert "name" in attachment_data
                assert "content_base64" in attachment_data
        else:
            assert False, "No emails with attachments found"


@pytest.mark.asyncio
async def test_search_files():
    """Test search_files tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "search_files",
            {"account_id": account_info["account_id"], "query": "test", "limit": 5},
        )
        assert not result.isError
        search_results = parse_result(result)
        assert search_results is not None


@pytest.mark.asyncio
async def test_search_emails():
    """Test search_emails tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "search_emails",
            {"account_id": account_info["account_id"], "query": "test", "limit": 5},
        )
        assert not result.isError
        search_results = parse_result(result)
        assert search_results is not None


@pytest.mark.asyncio
async def test_search_events():
    """Test search_events tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "search_events",
            {"account_id": account_info["account_id"], "query": "meeting", "limit": 5},
        )
        assert not result.isError
        search_results = parse_result(result)
        assert search_results is not None


@pytest.mark.asyncio
async def test_search_contacts():
    """Test search_contacts tool"""
    async for session in get_session():
        account_info = await get_account_info(session)
        result = await session.call_tool(
            "search_contacts",
            {
                "account_id": account_info["account_id"],
                "query": account_info["email"].split("@")[0],
                "limit": 5,
            },
        )
        assert not result.isError
        search_results = parse_result(result)
        assert search_results is not None
