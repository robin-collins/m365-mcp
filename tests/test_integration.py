import os
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

load_dotenv()


@pytest.mark.asyncio
async def test_all_mcp_tools():
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

            import json
            import base64
            from datetime import datetime, timedelta, timezone

            result = await session.call_tool("list_signed_in_accounts", {})
            assert not result.isError

            accounts = []
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    account = json.loads(content_item.text)
                    accounts.append(account)

            assert len(accounts) > 0
            my_email = accounts[0]["username"]
            print(f"✓ Found account: {my_email}")

            result = await session.call_tool(
                "send_email",
                {
                    "to": my_email,
                    "subject": f"MCP Test Email - {datetime.now().isoformat()}",
                    "body": "This is an automated test email from the Microsoft MCP integration tests.\n\nIf you're seeing this, the send_email tool is working correctly!",
                },
            )
            if result.isError and hasattr(result.content[0], "text"):
                print(f"Send email error: {result.content[0].text}")
            assert not result.isError
            print("✓ Sent test email to myself")

            result = await session.call_tool("read_latest_email", {"count": 3})
            assert not result.isError
            emails = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Read {len(emails)} latest emails")

            start_time = datetime.now(timezone.utc) + timedelta(days=7)
            end_time = start_time + timedelta(hours=1)
            result = await session.call_tool(
                "create_calendar_event",
                {
                    "subject": "MCP Integration Test Event",
                    "start_iso": start_time.isoformat(),
                    "end_iso": end_time.isoformat(),
                    "attendees": [my_email],
                },
            )
            assert not result.isError
            event_id = (
                result.content[0].text.strip('"')
                if hasattr(result.content[0], "text")
                else ""
            )
            print(f"✓ Created calendar event with ID: {event_id}")

            result = await session.call_tool("upcoming_events", {"days": 14})
            assert not result.isError
            events = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Found {len(events)} upcoming events")

            result = await session.call_tool("drive_info", {})
            assert not result.isError
            drive_info = (
                json.loads(result.content[0].text)
                if hasattr(result.content[0], "text")
                else {}
            )
            print(f"✓ Connected to {drive_info['driveType']} drive")

            test_content = f"MCP Integration Test\nGenerated at: {datetime.now().isoformat()}\nThis file was uploaded by the Microsoft MCP tests."
            content_b64 = base64.b64encode(test_content.encode()).decode()
            result = await session.call_tool(
                "upload_drive_file",
                {"path": "mcp-test.txt", "content_base64": content_b64},
            )
            assert not result.isError
            upload_result = (
                json.loads(result.content[0].text)
                if hasattr(result.content[0], "text")
                else {}
            )
            uploaded_file_id = upload_result["id"]
            print(f"✓ Uploaded test file with ID: {uploaded_file_id}")

            result = await session.call_tool("list_files_in_root", {"max_items": 20})
            assert not result.isError
            files = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Listed {len(files)} files in root")

            result = await session.call_tool(
                "download_drive_item", {"item_id": uploaded_file_id}
            )
            assert not result.isError
            downloaded_b64 = (
                result.content[0].text.strip('"')
                if hasattr(result.content[0], "text")
                else ""
            )
            downloaded_content = base64.b64decode(downloaded_b64).decode()
            assert downloaded_content == test_content
            print("✓ Downloaded and verified uploaded file")

            print("\n✅ All Microsoft MCP tools tested successfully!")
