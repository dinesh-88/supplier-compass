"""Test-only OpenAI-compatible endpoint for the Playwright smoke test (never used by the app itself).

Turn 1 of a chat with tools: call explain_index for the supplier ID in the question.
Turn 2: answer from the tool result. Requests without tools (memo prose) get one plain sentence.
"""

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self._send({"data": [{"id": "e2e-fake"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        tool_results = [json.loads(m["content"]) for m in msgs if m.get("role") == "tool"]
        if body.get("tools") and not tool_results:
            question = next(m["content"] for m in reversed(msgs) if m["role"] == "user")
            sid = (re.findall(r"SUPP_\d{5}", question) or ["SUPP_00018"])[0]
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "explain_index", "arguments": json.dumps({"id": sid})}}]}
        elif tool_results:
            e = tool_results[0]
            drivers = ", ".join(f"{d['label']} {d['points_above_average']:+.1f}" for d in e["top_drivers"][:3])
            msg = {"role": "assistant", "content": f"{e['supplierID']} has index {e['total_risk_index']:.0f}. Top drivers: {drivers}."}
        else:
            msg = {"role": "assistant", "content": "Review the shortlist below before awarding."}
        self._send({"choices": [{"message": msg}]})

    def _send(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
