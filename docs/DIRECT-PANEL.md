# Direct panel access

Open `/panel` and choose **Direct IP:port access**, or send `/panelremote direct`.
Confirm to enable HTTPS on the configured panel port (8399 by default) for any
IPv4 source. The tool creates a self-signed certificate and the panel firewall
rule, persists its settings, and restarts the panel through the existing suite
supervisor. The RDPSuite scheduled task restores these settings at Windows logon.

Open `https://PUBLIC_IP:8399/` in a browser and enter the panel token at sign-in.
The panel message provides plain links and a separate **Show login token** button.
It does not embed an automatic-login credential in the URL. Existing operator
tokens also remain usable. A self-signed certificate produces a browser warning.

The machine needs a public IP, or a router forwarding this port. A provider-level
firewall may also need to allow the port. Local success does not prove outside
reachability. This mode needs no additional application on client devices.

`/panelremote status` reports the configured network access; `/panelremote off`
returns to loopback HTTP and removes the managed remote rule. The `open`, `any`,
and `public` aliases retain compatibility and all require confirmation before
allowing public access. Restricted access remains available through
`/panelremote on` and `/panelremote allow IP`.
