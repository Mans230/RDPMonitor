package io.github.mans230.rdpmonitor.feature.overview

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.core.model.Snapshot
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun OverviewScreen(snapshot: Snapshot) {
    PageTitle("Overview", snapshot.host)
    Section("Memory", "Used memory across the Windows host") {
        Text(percent(snapshot.ram), style = ReadingStyle.copy(fontSize = 32.sp))
        LinearProgressIndicator(progress = { ((snapshot.ram ?: 0.0) / 100).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().height(4.dp), color = Signal, trackColor = Rule, strokeCap = StrokeCap.Butt)
        MetricRow("In use", bytes(snapshot.ramUsed), "${bytes(snapshot.ramTotal)} installed")
    }
    Section("Current readings") {
        MetricRow("Processor", percent(snapshot.cpu))
        HorizontalDivider(color = Rule)
        MetricRow("Download", rate(snapshot.downloadBps))
        MetricRow("Upload", rate(snapshot.uploadBps))
        HorizontalDivider(color = Rule)
        MetricRow("Active sessions", snapshot.sessions?.toString() ?: "—")
        snapshot.disks.forEach { MetricRow("Disk ${it.name}", percent(it.usedPercent), "${bytes(it.freeBytes)} free") }
    }
    Section("CPU & memory history", "One-minute readings · missing samples stay as gaps") {
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) { Text("— CPU", color = Signal); Text("— Memory", color = Muted) }
        if (snapshot.history.isEmpty()) Text("No history received. Current readings are still shown above.", color = Muted)
        else ResourceChart(snapshot.history)
    }
}
