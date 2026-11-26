# Android companion

Build a native Kotlin/Compose companion. Keep sample data clearly labelled.
Never copy production configuration, passkeys, cookies or Telegram credentials.
No production service/firewall/deployment changes belong to this app task.
Require exact private HTTPS origins and default certificate verification.
Use external-browser Passkey authorization plus PKCE for native pairing; never
extract browser cookies or introduce a shared bot token or insecure WebView.
Until the server pairing protocol is implemented and approved, show its absence
clearly. Preview operations must never execute real server changes.
