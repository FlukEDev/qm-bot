"""
Throwaway helper: run this ONCE to read your own LINE userId, then stop it.

It is not part of the running bot — the bot only ever pushes messages, it
never needs a webhook. This exists purely because LINE has no API to look up
a userId by name/phone; the only way to get it is to receive an event from
that user and read `events[0].source.userId`.

Usage:
    pip install fastapi uvicorn
    python webhook_capture.py                      # starts on :8000
    # in another terminal, expose it publicly, e.g.:
    cloudflared tunnel --url http://localhost:8000
    # (or `ngrok http 8000`)
    # then in LINE Developers Console > Messaging API tab:
    #   - set Webhook URL to https://<tunnel-domain>/line-webhook
    #   - click "Verify", then enable "Use webhook"
    # add the OA as a friend on your phone and send it any message.
    # your userId (starts with "U...") is printed below and saved to userid.txt.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/line-webhook")
async def line_webhook(req: Request):
    body = await req.json()
    for ev in body.get("events", []):
        source = ev.get("source", {})
        print("LINE event source:", source)
        if source.get("type") == "user":
            user_id = source["userId"]
            print(f"\n>>> Your userId: {user_id}\n>>> Put this in .env as LINE_TO_USER_ID\n")
            with open("userid.txt", "a") as f:
                f.write(user_id + "\n")
        elif source.get("type") == "group":
            print(f"\n>>> This groupId: {source['groupId']}\n")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
