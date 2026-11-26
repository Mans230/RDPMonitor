package io.github.mans230.rdpmonitor.feature.overview

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.layout.onSizeChanged
import io.github.mans230.rdpmonitor.core.model.Snapshot
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

/** Resource summary stays above the in-flow dock on every function view. */
@Composable fun OverviewScreen(snapshot: Snapshot) {
    PageTitle("Server overview", snapshot.host)
    BoxWithConstraints {
        val narrow = maxWidth < 280.dp
        val density = LocalDensity.current
        var processorHeight by remember { mutableIntStateOf(0) }
        val resourceHeight = with(density) { processorHeight.toDp() }
        if (maxWidth >= 760.dp) Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Column(Modifier.weight(2f).onSizeChanged { processorHeight = it.height }) { ProcessorCard(snapshot) }
            CapacityCard("Memory", snapshot.ram, "${bytes(snapshot.ramUsed)} / ${bytes(snapshot.ramTotal)}", Modifier.weight(1f).heightIn(min = resourceHeight))
            Box(Modifier.weight(1f)) { StorageCard(snapshot, Modifier.heightIn(min = resourceHeight)) }
        } else Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            ProcessorCard(snapshot)
            if (narrow) {
                CapacityCard("Memory", snapshot.ram, "${bytes(snapshot.ramUsed)} / ${bytes(snapshot.ramTotal)}")
                StorageCard(snapshot)
            } else Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                CapacityCard("Memory", snapshot.ram, "${bytes(snapshot.ramUsed)} / ${bytes(snapshot.ramTotal)}", Modifier.weight(1f))
                Box(Modifier.weight(1f)) { StorageCard(snapshot) }
            }
        }
    }
}
@Composable private fun ProcessorCard(snapshot: Snapshot) {
    Section("Processor", "Last 30 minutes · ${snapshot.cores?.let { "$it logical cores" } ?: "Core count unavailable"}") {
        Text(percent(snapshot.cpu), style = ReadingStyle.copy(fontSize = 32.sp))
        if (snapshot.history.isEmpty()) Text("No recorded CPU history received.", color = Muted)
        else ResourceChart(snapshot.history, cpuOnly = true)
    }
}
@Composable private fun StorageCard(snapshot: Snapshot, modifier: Modifier = Modifier) {
    val disk = snapshot.disks.firstOrNull()
    CapacityCard("Storage", disk?.usedPercent, disk?.let { "${it.name} · ${bytes(it.freeBytes)} free" } ?: "No disk readings", modifier)
}
@Composable private fun CapacityCard(title: String, value: Double?, detail: String, modifier: Modifier = Modifier) {
    BoxWithConstraints(modifier.fillMaxWidth(), propagateMinConstraints = true) {
        Column(Modifier.fillMaxWidth().border(1.dp, Rule, RoundedCornerShape(14.dp)).padding(if (maxWidth < 150.dp) 16.dp else 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(percent(value), style = ReadingStyle.copy(fontSize = 28.sp))
            LinearProgressIndicator(progress = { ((value ?: 0.0) / 100).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(3.dp), color = Signal, trackColor = Rule, strokeCap = StrokeCap.Butt)
            Text(detail, color = Muted, style = MaterialTheme.typography.bodySmall)
        }
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
