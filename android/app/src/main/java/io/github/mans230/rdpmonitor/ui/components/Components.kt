package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import io.github.mans230.rdpmonitor.core.model.ResourcePoint
import io.github.mans230.rdpmonitor.ui.theme.*
import java.util.Locale

fun percent(value: Double?) = value?.let { String.format(Locale.US, "%.1f%%", it) } ?: "—"
fun bytes(value: Long?): String {
    if (value == null) return "—"
    val unit = if (value >= 1_073_741_824L) 1_073_741_824.0 else 1_048_576.0
    return String.format(Locale.US, "%.1f %s", value / unit, if (unit > 1_048_576) "GiB" else "MiB")
}
fun rate(value: Double?) = value?.let { String.format(Locale.US, "%.1f Mbps", it * 8 / 1_000_000) } ?: "—"

@Composable fun Section(title: String, subtitle: String? = null, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Box(modifier) { CossFrame(title, subtitle) { CossPanel(content = content) } }
}
@Composable fun MetricRow(label: String, value: String, detail: String? = null) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(.45f)) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            detail?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodyMedium) }
        }
        Text(value, Modifier.weight(.55f), textAlign = androidx.compose.ui.text.style.TextAlign.End,
            style = ReadingStyle.copy(fontSize = 16.sp), color = if (value == "—") Muted else MaterialTheme.colorScheme.onSurface)
    }
}
@Composable fun PageTitle(title: String, detail: String) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, Modifier.testTag("page-title-$title"), style = MaterialTheme.typography.titleLarge)
        if (detail.isNotBlank()) Text(detail, style = MaterialTheme.typography.bodyMedium, color = Muted)
    }
}
@Composable fun Notice(text: String, warning: Boolean = false) {
    Row(Modifier.fillMaxWidth().border(1.dp, Rule, RoundedCornerShape(8.dp)).padding(12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(if (warning) "!" else "·", color = if (warning) Warning else Signal, fontWeight = FontWeight.Bold)
        Text(text, color = Muted, style = MaterialTheme.typography.bodyMedium)
    }
}
@Composable fun PulseMark() {
    Icon(CossIcons.Server, "RDPMonitor server", Modifier.size(20.dp), tint = Signal)
}

@Composable fun ResourceChart(points: List<ResourcePoint>, cpuOnly: Boolean = false, seriesName: String = "CPU") {
    val ink = Signal; val muted = Muted; val rule = Rule
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Column(Modifier.height(if (cpuOnly) 90.dp else 160.dp).width(32.dp), verticalArrangement = Arrangement.SpaceBetween) {
            listOf("100%", "50%", "0%").forEach { Text(it, color = Muted, fontSize = 11.sp) }
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Canvas(Modifier.fillMaxWidth().height(if (cpuOnly) 90.dp else 160.dp).semantics {
                contentDescription = if (cpuOnly) "$seriesName history, zero to one hundred percent. Missing samples are gaps." else "CPU and memory history, zero to one hundred percent. Missing samples are gaps."
            }) {
                repeat(3) { i -> drawLine(rule, Offset(0f, size.height * i / 2), Offset(size.width, size.height * i / 2), 1.dp.toPx()) }
                val timeRange = 1800 // Match the labelled 30-minute window, even with only a few samples.
                fun line(color: Color, get: (ResourcePoint) -> Double?) {
                    val path = Path(); var started = false
                    points.forEach { point ->
                        val value = get(point)
                        if (value == null) started = false else {
                            val x = size.width * (1 - point.secondsAgo.toFloat() / timeRange)
                            val y = size.height * (1 - value.coerceIn(0.0, 100.0).toFloat() / 100)
                            if (!started) path.moveTo(x, y) else path.lineTo(x, y)
                            started = true
                        }
                    }
                    drawPath(path, color, style = Stroke(2.dp.toPx()))
                }
                line(ink) { it.cpu }; if (!cpuOnly) line(muted) { it.ram }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                listOf("30 min ago", "15 min", "Now").forEach { Text(it, color = Muted, fontSize = 11.sp) }
            }
        }
    }
}
