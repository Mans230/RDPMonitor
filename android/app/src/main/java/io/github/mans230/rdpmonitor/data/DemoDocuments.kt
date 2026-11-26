package io.github.mans230.rdpmonitor.data

import kotlinx.serialization.json.*

/** Labelled offline fixtures only. Never passed to network or action methods. */
object DemoDocuments {
    fun at(path: String): JsonElement = Json.parseToJsonElement(when (path.substringBefore('?')) {
        "/api/setup" -> """{"backup":{"sources":["C:\\Projects","C:\\Documents"],"schedule":{"enabled":true,"mode":"daily","time":"03:00"},"timezone":"Server timezone"},"cloud":{"healthy":true,"version":"rclone","remotes":["drive:"],"image_target":"drive:Images","backup_targets":["drive:"],"folder":"Backups"},"images":{"enabled":true,"files":[{"path":"D:\\Images\\System.vhdx","size":53687091200,"modified":1795650000}],"phase":"done","percent":100},"remote":{"mode":"Private Tailscale","authentication":"Passkey"}}"""
        "/api/backup" -> """{"installed":true,"worker":{"state":"idle"},"last":{"state":"verified","files":42},"items":[{"name":"Backup_example.zip","size":524288000,"modified":1795650000}],"settings":{"schedule_enabled":true,"keep_local_copies":3}}"""
        "/api/rdp" -> """{"port":3389,"allow_active":true,"allowed_ips":["100.64.1.10"],"lockdown":false,"panic":false,"blocked_count":2}"""
        "/api/security" -> """{"blocked":{"203.0.113.10":{"reason":"Repeated failed logins"}},"sessions":[{"user":"demo-user","state":"active"}]}"""
        "/api/users" -> """{"items":[{"name":"demo-user","enabled":true},{"name":"backup-user","enabled":false}]}"""
        "/api/stats" -> """{"sessions":[{"user":"demo-user","session":"rdp-tcp#1","id":"2","state":"active"}]}"""
        "/api/services" -> """{"items":[{"name":"TermService","status":"Running","display_name":"Remote Desktop Services"}]}"""
        "/api/suite-update" -> """{"installed":{"version":"Sample release"},"automatic_updates":{"enabled":true,"hours":24},"status":"Up to date"}"""
        "/api/settings" -> """{"groups":[{"name":"Resource alerts","items":[{"key":"cpu","label":"CPU warning threshold","type":"number","value":80},{"key":"image_enabled","label":"System imaging","type":"bool","value":true}]}]}"""
        "/api/usage" -> """{"period":"Sample day","operations":8,"failed":0}"""
        "/api/mobile/v1/sessions" -> """{"items":[{"id":"sample-session","scope":"monitoring:read","created":1795650000,"expires":1795651800}]}"""
        "/api/setup/jobs" -> """{"jobs":[{"op":"authorize","state":"done","message":"Cloud account connected"}]}"""
        "/api/automation" -> """{"items":[{"name":"example-service.exe","ram_mb":1024}]}"""
        "/api/traps" -> """{"items":[{"name":"example-trap","enabled":true}]}"""
        else -> """{"status":"No sample entries"}"""
    })
}
