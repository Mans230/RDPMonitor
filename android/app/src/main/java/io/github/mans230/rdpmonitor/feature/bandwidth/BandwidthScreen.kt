package io.github.mans230.rdpmonitor.feature.bandwidth

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.core.model.Traffic
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun BandwidthScreen(traffic: Traffic?) {
    PageTitle("Bandwidth", "Machine-wide traffic, with an explicit accounting window.")
    if (traffic == null) { Notice("No bandwidth accounting has been received for this server. No usage totals are estimated."); return }
    Section("Billing-cycle usage", "Sample window · days 1–14") {
        Text(bytes(traffic.totalBytes), style = ReadingStyle.copy(fontSize = 30.sp))
        traffic.quotaFraction?.let { fraction ->
            LinearProgressIndicator(progress = { fraction.toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth(), color = Signal, trackColor = Rule)
            MetricRow("Plan", bytes(traffic.quotaBytes), "${"%.1f".format(java.util.Locale.US, fraction * 100)}% used")
        }
        MetricRow("Downloaded", bytes(traffic.downloadBytes))
        MetricRow("Uploaded", bytes(traffic.uploadBytes))
    }
    Section("Daily transfer", "Total download + upload · GiB") {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text("12 GiB", color = Muted); Text("Day 1–14", color = Muted) }
        Canvas(Modifier.fillMaxWidth().height(160.dp)) {
            repeat(3) { i -> drawLine(Rule, Offset(0f, size.height * i / 2), Offset(size.width, size.height * i / 2), 1.dp.toPx()) }
            val step = size.width / traffic.days.size.coerceAtLeast(1)
            traffic.days.forEachIndexed { i, day ->
                val height = size.height * (day.totalBytes / (12.0 * 1_073_741_824)).toFloat().coerceIn(0f, 1f)
                drawRect(Signal, Offset(i * step + step * .2f, size.height - height), androidx.compose.ui.geometry.Size(step * .6f, height))
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { listOf("1", "7", "14").forEach { Text(it, color = Muted) } }
    }
    Section("Daily ledger") {
        traffic.days.asReversed().take(7).forEach { MetricRow("Day ${it.label}", bytes(it.totalBytes)) }
    }
    Notice("Accounting can contain gaps while the monitor is stopped. An unavailable reading is not a measured zero.")
}
