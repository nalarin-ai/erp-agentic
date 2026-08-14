"""Chat channel ingress surface (FLOW-001, R-003/R-004).

Channels (WhatsApp/Telegram) are interaction surfaces only. This package will
hold the typed ingress adapter that resolves actor→channel bindings before
dispatching into workflows; the channel never touches business data directly.
"""
