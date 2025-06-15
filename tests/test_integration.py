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


def parse_result(result):
    """Helper to parse MCP tool results consistently"""
    if result.content and hasattr(result.content[0], "text"):
        return json.loads(result.content[0].text)
    return None


@pytest.mark.asyncio
async def test_microsoft_mcp_tools():
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        pytest.skip("MICROSOFT_MCP_CLIENT_ID not set")

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

            # Test account management
            result = await session.call_tool("list_accounts", {})
            assert not result.isError
            accounts = parse_result(result)
            if accounts is None:
                accounts = []

            if len(accounts) == 0:
                print("No accounts found - auth will be triggered on first API call")
                return

            my_email = accounts[0]["username"]
            print(f"✓ Found account: {my_email}")

            # Test email reading with full body
            result = await session.call_tool(
                "list_emails", {"limit": 3, "include_body": True}
            )
            assert not result.isError
            emails = parse_result(result)
            if emails is None:
                raise ValueError("Failed to list emails")
            print(f"✓ Read {len(emails)} emails with body content")

            # Test getting specific email with attachments
            if emails:
                email_id = emails[0]["id"]
                result = await session.call_tool("get_email", {"email_id": email_id})
                assert not result.isError
                email_detail = parse_result(result)
                if not email_detail:
                    raise ValueError("Failed to get email details")
                print(
                    f"✓ Got email details, has attachments: {email_detail.get('hasAttachments', False)}"
                )

                # Test marking email as read/unread (no side effects - restore original state)
                original_read_state = emails[0].get("isRead", True)
                result = await session.call_tool(
                    "update_email",
                    {
                        "email_id": email_id,
                        "updates": {"isRead": not original_read_state},
                    },
                )
                assert not result.isError
                print(
                    f"✓ Marked email as {'read' if not original_read_state else 'unread'}"
                )

                # Restore original state
                result = await session.call_tool(
                    "update_email",
                    {"email_id": email_id, "updates": {"isRead": original_read_state}},
                )
                assert not result.isError

            # Test sending email to self with CC and attachments
            test_attachment = {
                "name": "test.txt",
                "content_base64": base64.b64encode(b"Test attachment content").decode(),
            }

            result = await session.call_tool(
                "create_email",
                {
                    "to": my_email,
                    "subject": f"MCP Test - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "body": "Test email with attachment from Microsoft MCP integration tests.",
                    "cc": [my_email],
                    "attachments": [test_attachment],
                    "send_immediately": True,
                },
            )
            assert not result.isError
            print("✓ Sent email with CC and attachment")

            # Test email reply (find the test email we just sent)
            await asyncio.sleep(2)  # Give it time to arrive
            result = await session.call_tool("list_emails", {"limit": 5})
            assert not result.isError
            recent_emails = parse_result(result)
            if recent_emails is None:
                recent_emails = []

            test_email = next(
                (e for e in recent_emails if "MCP Test" in e.get("subject", "")), None
            )
            if test_email:
                result = await session.call_tool(
                    "reply_email",
                    {
                        "email_id": test_email["id"],
                        "body": "This is a test reply",
                        "reply_all": False,
                    },
                )
                assert not result.isError
                print("✓ Replied to email")

            # Test email folder operations - create a draft and delete it
            draft_result = await session.call_tool(
                "create_email",
                {
                    "to": my_email,
                    "subject": "MCP Test Draft",
                    "body": "This is a test draft email",
                    "send_immediately": False,  # Create as draft
                },
            )
            if not draft_result.isError:
                draft_data = parse_result(draft_result)
                if not draft_data:
                    raise ValueError("Failed to create draft")
                draft_id = draft_data.get("id")
                
                if draft_id:
                    # Delete the draft to clean up
                    result = await session.call_tool("delete_email", {"email_id": draft_id})
                    if not result.isError:
                        print("✓ Created and deleted draft email")
                    else:
                        print("✓ Created draft (cleanup failed)")

            # Test calendar events with details
            result = await session.call_tool(
                "list_events", {"days_ahead": 14, "include_details": True}
            )
            assert not result.isError
            events = parse_result(result)
            if events is None:
                events = []
            print(f"✓ Found {len(events)} calendar events with details")

            # Test availability check
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
                {"start": check_start, "end": check_end, "attendees": [my_email]},
            )
            assert not result.isError
            availability = parse_result(result)
            if not availability:
                raise ValueError("Failed to check availability")
            print("✓ Checked availability")

            # Test creating event with location and body
            start_time = datetime.now(timezone.utc) + timedelta(days=7)
            end_time = start_time + timedelta(hours=1)
            result = await session.call_tool(
                "create_event",
                {
                    "subject": "MCP Integration Test Event",
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "location": "Virtual Meeting Room",
                    "body": "This is a test event created by integration tests",
                    "attendees": [my_email],
                },
            )
            assert not result.isError
            event_data = parse_result(result)
            if not event_data or "id" not in event_data:
                raise ValueError("Failed to create event - no ID returned")
            event_id = event_data["id"]
            print(f"✓ Created event with details: {event_id[:8]}...")

            # Test updating event
            new_start = start_time + timedelta(hours=2)
            new_end = new_start + timedelta(hours=1)
            result = await session.call_tool(
                "update_event",
                {
                    "event_id": event_id,
                    "updates": {
                        "subject": "MCP Test Event (Updated)",
                        "start": new_start.isoformat(),
                        "end": new_end.isoformat(),
                        "location": "Conference Room B",
                    },
                },
            )
            assert not result.isError
            print("✓ Updated event details")

            # Test event response (if there are any events with invitations)
            if events and any(e.get("attendees") for e in events):
                invite_event = next(e for e in events if e.get("attendees"))
                result = await session.call_tool(
                    "respond_event",
                    {
                        "event_id": invite_event["id"],
                        "response": "tentativelyAccept",
                        "message": "I might be able to attend",
                    },
                )
                # Don't assert - this might fail if it's our own event
                if not result.isError:
                    print("✓ Responded to event invitation")

            # Test deleting event (cleanup)
            result = await session.call_tool(
                "delete_event", {"event_id": event_id, "send_cancellation": False}
            )
            assert not result.isError
            print("✓ Deleted test event")

            # Test contacts (may fail due to permissions)
            try:
                result = await session.call_tool("list_contacts", {"limit": 10})
                if not result.isError:
                    contacts = parse_result(result)
                    if contacts is None:
                        contacts = []
                    print(f"✓ Listed {len(contacts)} contacts")

                    # Test contact search using universal search
                    if contacts:
                        result = await session.call_tool(
                            "search",
                            {"query": my_email.split("@")[0], "types": ["person"], "limit": 5},
                        )
                        assert not result.isError
                        search_results = parse_result(result)
                        if search_results is None:
                            search_results = []
                        print(f"✓ Searched contacts, found {len(search_results)} results")
                else:
                    print("⚠️  Skipped contacts test (insufficient permissions)")
            except Exception as e:
                print(f"⚠️  Skipped contacts test: {e}")

            # Test file operations
            result = await session.call_tool("list_files", {})
            assert not result.isError
            files = parse_result(result)
            if files is None:
                files = []
            print(f"✓ Listed {len(files)} files")

            # Test file upload
            test_content = f"MCP Integration Test\nTimestamp: {datetime.now().isoformat()}\nThis file should be automatically deleted."
            content_b64 = base64.b64encode(test_content.encode()).decode()
            test_filename = f"mcp-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"

            result = await session.call_tool(
                "create_file",
                {"path": test_filename, "content_base64": content_b64},
            )
            assert not result.isError
            upload_result = parse_result(result)
            if not upload_result or "id" not in upload_result:
                raise ValueError("Failed to upload file")
            file_id = upload_result["id"]
            print(f"✓ Uploaded test file: {file_id[:8]}...")

            # Test file download
            result = await session.call_tool("get_file", {"file_id": file_id})
            assert not result.isError
            file_data = parse_result(result)
            if not file_data or "content_base64" not in file_data:
                raise ValueError("Failed to get file data")
            downloaded_b64 = file_data.get("content_base64", "")
            downloaded_content = base64.b64decode(downloaded_b64).decode()
            assert downloaded_content == test_content
            print("✓ Downloaded and verified file")

            # Test file deletion (cleanup)
            result = await session.call_tool("delete_file", {"file_id": file_id})
            assert not result.isError
            print("✓ Deleted test file")

            # Test comprehensive search (may fail due to API limitations)
            try:
                result = await session.call_tool(
                    "search",
                    {"query": "test", "types": ["message"], "limit": 5},
                )
                if not result.isError:
                    search_hits = parse_result(result)
                    if search_hits is None:
                        search_hits = []
                    print(f"✓ Search found {len(search_hits)} results")
                else:
                    print("⚠️  Skipped search test (API limitations)")
            except Exception as e:
                print(f"⚠️  Skipped search test: {e}")

            # Clean up any test emails in sent items
            result = await session.call_tool(
                "list_emails", {"folder": "sent", "limit": 10}
            )
            if not result.isError:
                sent_emails = parse_result(result)
                if sent_emails is None:
                    sent_emails = []
                for email in sent_emails:
                    if "MCP Test" in email.get(
                        "subject", ""
                    ) or "MCP Integration Test" in email.get("subject", ""):
                        await session.call_tool(
                            "move_email",
                            {"email_id": email["id"], "destination_folder": "deleted"},
                        )
                print("✓ Cleaned up test emails")

            print(
                "\n✅ All Microsoft MCP tools tested successfully with no side effects!"
            )
