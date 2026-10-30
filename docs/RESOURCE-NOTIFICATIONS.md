# Resource notifications

CPU and RAM share one incident. A normal warning must persist for 120 seconds;
danger and critical thresholds notify immediately. A higher severity notifies
immediately, while a lower severity does not create a fresh notification.

The incident closes only when both resources stay at least five percentage
points below their respective warning thresholds for 180 seconds. A brief dip
does not reset notification timing. Recovery is sent once, only for an incident
that produced a notification, with duration and peak CPU/RAM readings.

An unchanged elevated severity can remind at most every 30 minutes (or the
configured alert interval, if longer). Spike context is combined with threshold
notifications. Standalone spikes retain their existing cooldown. Muting retains
its existing behavior. Incident state resets when the monitor restarts.

Threshold percentages remain user-configured; the policy does not raise them
automatically. For example, RAM bouncing between 48% and 51% with a 50% warning
limit no longer produces alternating warning and recovery messages.

## Permanent remote panel access

Open `/panelremote` from the Telegram menu to review restricted HTTPS access,
access from anywhere, connection status, or disabling remote access. Remote
settings are saved in `webconsole/webconsole_state.json`; the existing RDPSuite
scheduled task starts the panel with these settings after logon. An HTTPS
certificate, application IP policy, and matching firewall rule are maintained by
the existing remote-mode commands. A self-signed certificate requires browser
trust or replacement with a certificate trusted by the client.
