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
        "/api/suite-update" -> """{"installed":true,"current":"sample-commit","settings":{"enabled":true,"interval_hours":24},"state":{"phase":"current","message":"Up to date"},"next_check":1795736400}"""
        "/api/settings" -> """{"groups":[{"name":"Resource alerts","items":[{"key":"cpu","label":"CPU warning threshold","type":"number","value":80},{"key":"image_enabled","label":"System imaging","type":"bool","value":true}]}]}"""
        "/api/usage" -> """{"events":8,"by_actor":{"owner":8},"by_action":{"backup_now":7,"test_alert":1},"by_status":{"ok":8}}"""
        "/api/mobile/v1/sessions" -> """{"items":[{"id":"sample-session","scope":"monitoring:read","created":1795650000,"expires":1795651800}]}"""
        "/api/setup/jobs" -> """{"jobs":[{"op":"authorize","state":"done","message":"Cloud account connected"}]}"""
        "/api/automation" -> if (path.contains("list=svcwatch")) """{"items":[{"name":"TermService"}]}""" else """{"items":[{"name":"example-service.exe","ram_mb":1024}]}"""
        "/api/sysinfo" -> """{"hostname":"Preview Windows server","os":"Windows Server 2022","version":"Sample build","arch":"AMD64","cores":8,"ram_total":12884901888,"uptime_s":86400,"boot":1795650000,"disks":[{"dev":"C:\\","total":214748364800,"free":141733920768}]}"""
        "/api/traps" -> """{"items":[{"name":"example-trap","enabled":true}]}"""
        else -> """{"status":"No sample entries"}"""
    })
}
