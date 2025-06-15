import os
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

load_dotenv()


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

            import json
            import base64
            from datetime import datetime, timedelta, timezone

            result = await session.call_tool("list_accounts", {})
            assert not result.isError
            
            accounts = []
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    account = json.loads(content_item.text)
                    accounts.append(account)
            
            if len(accounts) == 0:
                print("No accounts found - auth will be triggered on first API call")
                return
                
            my_email = accounts[0]["username"]
            print(f"✓ Found account: {my_email}")

            result = await session.call_tool(
                "send_email",
                {
                    "to": my_email,
                    "subject": f"MCP Test - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "body": "Test email from Microsoft MCP integration tests.",
                },
            )
            assert not result.isError
            print("✓ Sent test email")

            result = await session.call_tool("read_emails", {"count": 3})
            assert not result.isError
            emails = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Read {len(emails)} emails")

            start_time = datetime.now(timezone.utc) + timedelta(days=7)
            end_time = start_time + timedelta(hours=1)
            result = await session.call_tool(
                "create_event",
                {
                    "subject": "MCP Test Event",
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                },
            )
            assert not result.isError
            event_id = (
                result.content[0].text.strip('"')
                if hasattr(result.content[0], "text")
                else ""
            )
            print(f"✓ Created event: {event_id[:8]}...")

            result = await session.call_tool("get_calendar_events", {"days": 14})
            assert not result.isError
            events = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Found {len(events)} calendar events")

            test_content = f"MCP Test\n{datetime.now().isoformat()}"
            content_b64 = base64.b64encode(test_content.encode()).decode()
            result = await session.call_tool(
                "upload_file",
                {"path": "mcp-test.txt", "content_base64": content_b64},
            )
            assert not result.isError
            upload_result = (
                json.loads(result.content[0].text)
                if hasattr(result.content[0], "text")
                else {}
            )
            file_id = upload_result["id"]
            print(f"✓ Uploaded file: {file_id[:8]}...")

            result = await session.call_tool("list_files", {})
            assert not result.isError
            files = [
                json.loads(item.text)
                for item in result.content
                if hasattr(item, "text")
            ]
            print(f"✓ Listed {len(files)} files")

            result = await session.call_tool(
                "download_file", {"file_id": file_id}
            )
            assert not result.isError
            downloaded_b64 = (
                result.content[0].text.strip('"')
                if hasattr(result.content[0], "text")
                else ""
            )
            downloaded_content = base64.b64decode(downloaded_b64).decode()
            assert downloaded_content == test_content
            print("✓ Downloaded and verified file")

            result = await session.call_tool(
                "delete_file", {"file_id": file_id}
            )
            assert not result.isError
            print("✓ Deleted test file")

            result = await session.call_tool(
                "search", {"query": "MCP Test"}
            )
            assert not result.isError
            print("✓ Search completed")

            print("\n✅ All Microsoft MCP tools tested successfully!")