package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

enum class Feature(val title: String, val summary: String, val capabilities: List<String>) {
    Protection("Protection", "RDP policy, firewall and account safety", listOf("RDP connectivity diagnostics", "Failed logins and grouped incidents", "Trusted IPs and blocked addresses", "Review before changing access")),
    Backups("Backups", "Archives, restore checks and schedules", listOf("Verified backup status", "Sources, retention and schedules", "Cloud destinations", "Restore and recovery review")),
    RdpAccess("RDP & users", "Sessions, access and local accounts", listOf("Active Windows sessions", "Local user inventory", "Session and account auditing", "Explicit confirmation for account changes")),
    Cloud("Cloud & images", "Guided cloud setup and system images", listOf("rclone account setup", "Backup and image upload destinations", "System image progress", "Archive and image verification")),
    Commands("Command center", "Commands grouped by their purpose", listOf("CPU & RAM", "Network & bandwidth", "Protection & accounts", "Programs & services", "Backups & recovery", "Settings & maintenance")),
    Updates("Updates", "Validated bot and panel releases", listOf("Current release and health", "Checksummed suite updates", "Installation status and rollback", "Preserve approved passkeys")),
    Access("Private access", "Tailscale, passkeys and owner approval", listOf("HTTPS over the private tailnet", "Passkey sign-in in the system browser", "Owner approval in Telegram", "No chat login tokens or public IP fallback")),
    Settings("Settings & alerts", "Monitoring thresholds, notifications and permissions", emptyList()),
    Processes("Processes", "Current CPU, memory and process controls", emptyList()),
    LocalUsers("Local users", "Local accounts and reviewed account changes", emptyList()),
    History("Resource history", "Recorded CPU, memory, network and storage", emptyList()),
    SystemTools("System tools", "Services and programs", emptyList()),
    Automation("Automation", "Watch, keep alive and process rules", emptyList()),
    Diagnostics("Diagnostics", "Read-only server reports", emptyList()),
    Reference("Command reference", "Server command documentation", emptyList()),
    Maintenance("Maintenance", "Cleanup, logs and power controls", emptyList())
}

@Composable fun MoreScreen(onFeature: (Feature) -> Unit, onConnections: () -> Unit) {
    PageTitle("All sections", "Monitor, protect and maintain your server.")
    Section("Server tools") {
        Feature.entries.forEachIndexed { i, feature ->
            if (i > 0) HorizontalDivider(color = Rule)
            Row(Modifier.fillMaxWidth().clickable { onFeature(feature) }.padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(feature.title, style = MaterialTheme.typography.bodyLarge)
                    Text(feature.summary, color = Muted, style = MaterialTheme.typography.bodyMedium)
                }
                Icon(Icons.AutoMirrored.Outlined.ArrowForward, "Open ${feature.title}", tint = Muted, modifier = Modifier.size(20.dp))
            }
        }
    }
    OutlinedButton(onClick = onConnections, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Server connections") }
}

@Composable fun FeatureScreen(feature: Feature, demo: Boolean, onBack: () -> Unit, openPanel: (() -> Unit)?) {
    TextButton(onClick = onBack) { Text("Back to tools") }
    PageTitle(feature.title, feature.summary)
    Section("${feature.title} workflow") {
        feature.capabilities.forEach { Text(it, style = MaterialTheme.typography.bodyLarge) }
    }
    Notice(if (demo) "Preview only. These workflows cannot change a server. Connect to your server to use its web panel."
        else "Use the authenticated web panel for these operations. Server changes require review and confirmation.")
    openPanel?.let { Button(onClick = it, modifier = Modifier.fillMaxWidth()) { Text("Open authenticated web panel") } }
}
