package io.github.mans230.rdpmonitor.feature.overview

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.data.DemoDocuments
import io.github.mans230.rdpmonitor.feature.more.Feature
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

@Composable fun FunctionBoard(state: AppState, model: RdpViewModel, open: (Feature) -> Unit) {
    val snapshot = state.snapshot ?: return
    val paths = listOf("/api/setup", "/api/backup", "/api/rdp")
    LaunchedEffect(state.selected?.id, state.demo, state.administration) {
        if (!state.demo && state.administration && state.connected) model.loadDocuments(paths)
    }
    fun document(path: String) = if (state.demo) DemoDocuments.at(path) else state.documents[path]
    val lead = backupLead(document("/api/setup"), document("/api/backup"))
    val rdp = document("/api/rdp") as? JsonObject
    val blocked = (rdp?.get("blocked_count") as? JsonPrimitive)?.intOrNull
    val allow = (rdp?.get("allow_active") as? JsonPrimitive)?.booleanOrNull
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        PageTitle("Server functions", "Scheduled work first. Quick checks below.")
        if (!state.demo && !state.administration) Notice("Monitoring session · backup and protection details require administration approval. Open a function to review access.")
        paths.forEach { path -> state.documentErrors[path]?.let { Notice(it, true) } }
        if (state.documentLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
        BoxWithConstraints {
            val leadCard: @Composable () -> Unit = {
                GlassSurface(Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = "Review backup schedule") { open(Feature.Backups) }) {
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Text("Next backup", style = MaterialTheme.typography.bodyLarge)
                        Text(if (state.documentLoading && document("/api/setup") == null) "Loading…" else lead.value, style = ReadingStyle.copy(fontSize = 30.sp))
                        Text(lead.schedule, color = Muted, style = MaterialTheme.typography.bodySmall)
                        Text(lead.lastRun, color = Muted, style = MaterialTheme.typography.bodySmall)
                        OpenRow("Review schedule")
                    }
                }
            }
            val support: @Composable () -> Unit = {
                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    BoxWithConstraints {
                        val protection = listOfNotNull(blocked?.let { "$it blocked" }, allow?.let { "Allowlist ${if (it) "on" else "off"}" }).joinToString(" · ").ifEmpty { "Policy details unavailable" }
                        if (maxWidth < 280.dp) {
                            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                FunctionCard("Protection", protection, Modifier, { open(Feature.Protection) })
                                FunctionCard("Processes", "${snapshot.processes.size} reported · ${percent(snapshot.cpu)} CPU", Modifier, { open(Feature.Processes) })
                            }
                        } else Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                            FunctionCard("Protection", protection, Modifier.weight(1f), { open(Feature.Protection) })
                            FunctionCard("Processes", "${snapshot.processes.size} reported · ${percent(snapshot.cpu)} CPU", Modifier.weight(1f), { open(Feature.Processes) })
                        }
                    }
                    Surface(Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = "Open RDP access") { open(Feature.RdpAccess) }, shape = RoundedCornerShape(14.dp), color = Color.Transparent, border = BorderStroke(1.dp, Rule)) {
                        Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text("RDP access")
                                Text("${snapshot.sessions?.let { "$it sessions" } ?: "Sessions unavailable"} · Port ${(rdp?.get("port") as? JsonPrimitive)?.contentOrNull ?: "unavailable"}", color = Muted, style = MaterialTheme.typography.bodySmall)
                            }
                            Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(18.dp))
                        }
                    }
                }
            }
            if (maxWidth >= 760.dp) Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Box(Modifier.weight(1f)) { leadCard() }; Box(Modifier.weight(2f)) { support() }
            } else Column(verticalArrangement = Arrangement.spacedBy(16.dp)) { leadCard(); support() }
        }
        Section("Remote sessions", snapshot.sessions?.let { "$it reported sessions" } ?: "Session count unavailable", modifier = Modifier.padding(top = 12.dp)) {
            if (snapshot.remoteSessions.isEmpty()) Text(if (snapshot.sessions == 0) "No remote sessions reported." else "Session details not reported.", color = Muted)
            snapshot.remoteSessions.forEach { session ->
                MetricRow(session.user, session.state, "${session.name} · Session ${session.id.ifBlank { "unavailable" }}")
            }
            TextButton(onClick = { open(Feature.RdpAccess) }) { Text("Manage RDP & users") }
        }
    }
}

@Composable private fun FunctionCard(title: String, summary: String, modifier: Modifier, onClick: () -> Unit) {
    Surface(modifier.clickable(role = Role.Button, onClickLabel = "Open $title", onClick = onClick), shape = RoundedCornerShape(14.dp), color = Color.Transparent, border = BorderStroke(1.dp, Rule)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(title); Text(summary, color = Muted, style = MaterialTheme.typography.bodyMedium); OpenRow("Open")
        }
    }
}
@Composable private fun OpenRow(label: String) {
    Row(Modifier.fillMaxWidth().heightIn(min = 44.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodySmall)
        Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(16.dp))
    }
}
