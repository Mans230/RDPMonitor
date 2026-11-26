package io.github.mans230.rdpmonitor.feature.overview

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.AppState
import io.github.mans230.rdpmonitor.core.model.Snapshot
import io.github.mans230.rdpmonitor.data.DemoDocuments
import io.github.mans230.rdpmonitor.feature.more.backupDetails
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

/** Only recorded resource data and the two requested health facts live on Overview. */
@Composable fun OverviewScreen(snapshot: Snapshot, state: AppState) {
    var metric by rememberSaveable { mutableIntStateOf(0) }
    PageTitle("Server overview", snapshot.host)
    CossFrame("Server resources", "Recorded on this Windows host") {
        CossPanel {
            ResourceMeter("CPU", snapshot.cpu, snapshot.cores?.let { "$it logical processors" } ?: "Core count unavailable")
            ResourceMeter("Memory", snapshot.ram, "${bytes(snapshot.ramUsed)} of ${bytes(snapshot.ramTotal)}")
            val disk = snapshot.disks.firstOrNull()
            ResourceMeter(disk?.let { "Storage ${it.name}" } ?: "Storage", disk?.usedPercent,
                disk?.let { "${bytes(it.freeBytes)} free${it.totalBytes?.let { total -> " of ${bytes(total)}" }.orEmpty()}" } ?: "Disk reading unavailable")
        }
        CossPanel {
            Text("Resource history", style = MaterialTheme.typography.titleMedium)
            CossSegments(listOf("CPU", "RAM"), metric, { metric = it }, Modifier.widthIn(max = 260.dp))
            if (snapshot.history.isEmpty()) Text("No recorded ${if (metric == 0) "CPU" else "memory"} history received.", color = Muted)
            else ResourceChart(if (metric == 0) snapshot.history else snapshot.history.map { it.copy(cpu = it.ram) },
                cpuOnly = true, seriesName = if (metric == 0) "CPU" else "Memory")
            Text("Last 30 minutes. Missing samples remain gaps.", color = Muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    fun document(path: String) = if (state.demo) DemoDocuments.at(path) else state.documents[path]
    val backup = backupDetails(document("/api/backup"), document("/api/setup"))
    val uptime = ((document("/api/sysinfo") as? JsonObject)?.get("uptime_s") as? JsonPrimitive)?.doubleOrNull
    CossFrame("Server status", "Server-reported values. Refresh to update.") {
        CossPanel {
            MetricRow("Server uptime", uptimeText(uptime))
            HorizontalDivider(color = Rule)
            MetricRow("Latest backup result", backup.result)
            if (!state.demo && !state.administration) Text("Uptime and backup details require administration approval.", color = Muted, style = MaterialTheme.typography.bodySmall)
            listOf("/api/sysinfo", "/api/backup").forEach { path -> state.documentErrors[path]?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) } }
        }
    }
}

@Composable private fun ResourceMeter(label: String, value: Double?, note: String) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        MetricRow(label, percent(value))
        if (value != null) LinearProgressIndicator(progress = { (value / 100).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().height(6.dp), color = Signal, trackColor = Tray,
            strokeCap = StrokeCap.Butt, drawStopIndicator = {})
        Text(note, color = Muted, style = MaterialTheme.typography.bodySmall)
    }
}
@Composable fun ResourceHistory(snapshot: Snapshot) {
    PageTitle("Resource history", "Recorded CPU and memory · last 30 minutes")
    Section("CPU & memory", "One-minute readings · missing samples stay as gaps") {
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) { Text("— CPU", color = Signal); Text("— Memory", color = Muted) }
        if (snapshot.history.isEmpty()) Text("No history received.", color = Muted) else ResourceChart(snapshot.history)
    }
    Section("Network & storage") {
        MetricRow("Download", rate(snapshot.downloadBps)); MetricRow("Upload", rate(snapshot.uploadBps))
        snapshot.disks.forEach { MetricRow("Disk ${it.name}", percent(it.usedPercent), "${bytes(it.freeBytes)} free") }
    }
}
