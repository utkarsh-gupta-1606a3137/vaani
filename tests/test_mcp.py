"""Adapter tests; run with the optional MCP interpreter after --setup."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

try:
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from vaani import mcp as adapter
except ModuleNotFoundError:
    adapter = None


@unittest.skipIf(adapter is None, "Run bin/vaani-mcp --setup for MCP tests")
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_and_unique_absolute_output(self):
        with patch.object(adapter, "run_cli", new_callable=AsyncMock, return_value={}) as run:
            await adapter.generate_narration(content="नमस्ते, hello.")
            first, text = run.call_args.args
            await adapter.generate_narration(content="नमस्ते, hello.")
            second = run.call_args.args[0]
        self.assertEqual(text, "नमस्ते, hello.")
        self.assertIn("--stdin", first)
        self.assertNotIn("--voice", first)
        self.assertNotIn("--format", first)
        self.assertTrue(Path(first[1]).is_absolute())
        self.assertEqual(Path(first[1]).suffix, ".wav")
        self.assertNotEqual(first[1], second[1])

    async def test_all_options_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = str(Path(tmp).resolve() / "input with spaces.md")
            output = str(Path(tmp).resolve() / "output.mp3")
            job = str(Path(tmp).resolve() / "job")
            with patch.object(adapter, "run_cli", new_callable=AsyncMock, return_value={}) as run:
                await adapter.generate_narration(
                    content_file=source, output_path=output, voice="saba",
                    output_format="mp3", input_format="markdown", normalization="none",
                    seed=0, overwrite=True, resume_job_dir=job,
                    chunk_timeout_seconds=42, job_timeout_seconds=120,
                )
            args, text = run.call_args.args
            self.assertIsNone(text)
            for flag, value in (("--input", source), ("--output", output),
                                ("--voice", "saba"), ("--format", "mp3"),
                                ("--input-format", "markdown"), ("--normalization", "none"),
                                ("--seed", "0"), ("--resume", job),
                                ("--chunk-timeout", "42"), ("--job-timeout", "120")):
                self.assertEqual(args[args.index(flag) + 1], value)
            self.assertIn("--overwrite", args)
            self.assertNotIn("--stdin", args)

    async def test_invalid_input_never_starts_cli(self):
        invalid = [{}, {"content": ""}, {"content": "  "},
                   {"content": "hello", "content_file": "/tmp/in.txt"},
                   {"content_file": "relative.txt"},
                   {"content": "hello", "output_path": "relative.wav"},
                   {"resume_job_dir": "relative-job"}]
        with patch.object(adapter, "run_cli", new_callable=AsyncMock) as run:
            for kwargs in invalid:
                with self.subTest(kwargs=kwargs), self.assertRaises(adapter.ToolError):
                    await adapter.generate_narration(**kwargs)
            run.assert_not_called()

    async def test_resume_without_content(self):
        with patch.object(adapter, "run_cli", new_callable=AsyncMock, return_value={}) as run:
            await adapter.generate_narration(resume_job_dir="/tmp/job")
            self.assertIn("--resume", run.call_args.args[0])
            self.assertIsNone(run.call_args.args[1])

    async def test_protocol_schema_validation_and_structured_result(self):
        result = {"status": "complete", "output_file": "/tmp/test.wav"}
        async with Client(adapter.server) as client:
            listing = await client.list_tools()
            tool = listing.tools[0]
            self.assertEqual(tool.name, "generate_narration")
            self.assertIn("Hinglish", tool.description)
            self.assertEqual(tool.input_schema["properties"]["content"]["default"], None)
            for arguments in ({"content": "hi", "voice": "missing"},
                              {"content": "hi", "seed": -1},
                              {"content": "hi", "job_timeout_seconds": 0},
                              {"content": "hi", "output_format": "ogg"},
                              {"content": "x" * 100001}, {}):
                response = await client.call_tool(tool.name, arguments)
                self.assertTrue(response.is_error)
            with patch.object(adapter, "run_cli", new_callable=AsyncMock, return_value=result):
                response = await client.call_tool(tool.name, {"content": "hi"})
                self.assertFalse(response.is_error)
                self.assertEqual(response.structured_content, result)

    async def test_stdio_launcher_from_unrelated_directory(self):
        launcher = Path(__file__).resolve().parents[1] / "bin/vaani-mcp"
        with tempfile.TemporaryDirectory() as tmp:
            config = StdioServerParameters(command=str(launcher), cwd=tmp,
                                           env={**os.environ, "VAANI_ROOT": "/wrong", "PYTHONPATH": "/wrong"})
            async with Client(config, read_timeout_seconds=30) as client:
                listing = await client.list_tools()
                self.assertEqual(listing.tools[0].name, "generate_narration")
                response = await client.call_tool("generate_narration", {
                    "content_file": str(Path(tmp) / "missing.txt"),
                    "output_path": str(Path(tmp) / "out.wav"),
                })
                self.assertTrue(response.is_error)
                self.assertIn("Cannot read input", str(response.content))
                self.assertFalse((Path(tmp) / "out.wav").exists())

    async def test_cancellation_interrupts_cli_and_waits_for_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            marker = root / "cancelled"
            script = root / "bin/vaani"
            # Use the same interpreter as the tests, with a SIGINT cleanup hook.
            import sys
            script.write_text(f"#!{sys.executable}\nimport signal,time,pathlib\n"
                              f"def stop(*_):\n pathlib.Path({str(marker)!r}).touch()\n raise SystemExit(130)\n"
                              "signal.signal(signal.SIGINT, stop)\nprint('ready', flush=True)\ntime.sleep(30)\n")
            script.chmod(0o755)
            with patch.object(adapter, "project_root", return_value=root):
                with anyio.move_on_after(1) as scope:
                    await adapter.run_cli([], None)
            self.assertTrue(scope.cancel_called)
            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
