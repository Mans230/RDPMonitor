package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.core.model.Incident
import io.github.mans230.rdpmonitor.data.*
import io.github.mans230.rdpmonitor.feature.bandwidth.BandwidthScreen
import io.github.mans230.rdpmonitor.feature.activity.ActivityScreen
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

@Composable fun LiveBandwidth(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit) {
    val paths = if (state.administration) listOf("/api/bandwidth/usage", "/api/bandwidth/connections") else listOf("/api/bandwidth/usage")
    LaunchedEffect(state.selected?.id, state.demo) { model.loadDocuments(paths) }
    CossOutlinedButton(onClick = { model.loadDocuments(paths) }, enabled = !state.documentLoading) { Text(if (state.documentLoading) "Refreshing…" else "Refresh bandwidth") }
    val result = state.documents["/api/bandwidth/usage"]
    val traffic = result?.let { runCatching { SnapshotDecoder.traffic(it) } }
    state.documentErrors["/api/bandwidth/usage"]?.let { Notice(it, true) }
    traffic?.exceptionOrNull()?.let { Notice(it.message ?: "Invalid accounting data.", true) }
    BandwidthScreen(traffic?.getOrNull())
    (result as? JsonObject)?.let { data ->
        Section("Accounting quality") {
            listOf("collected_at", "timezone", "recorded_start", "measurement", "history_error").forEach { key ->
                data[key]?.let { Text(key.replace('_', ' '), color = Muted); NativeDocument(it, openBrowser) }
            }
        }
    }
    state.documentErrors["/api/bandwidth/connections"]?.let { Notice(it, true) }
    state.documents["/api/bandwidth/connections"]?.let { Section("Connections and adapters") { NativeDocument(it, openBrowser) } }
}

@Composable fun LiveActivity(state: AppState, model: RdpViewModel, processesOnly: Boolean = false) {
    val paths = if (state.administration) listOf("/api/audit", "/api/usage") else listOf("/api/audit")
    LaunchedEffect(state.selected?.id, state.demo, processesOnly) { if (!processesOnly) model.loadDocuments(paths) }
    if (!processesOnly) CossOutlinedButton(onClick = { model.loadDocuments(paths) }, enabled = !state.documentLoading) { Text("Refresh activity") }
    state.documentErrors["/api/audit"]?.let { Notice(it, true) }
    val items = ((state.documents["/api/audit"] as? JsonObject)?.get("items") as? JsonArray).orEmpty()
    val events = items.mapNotNull { it as? JsonObject }.asReversed().map { latest ->
        val name = latest["action"]?.jsonPrimitive?.content ?: "Event"
        val detail = latest["detail"]?.jsonPrimitive?.content.orEmpty()
        val at = latest["t"]?.jsonPrimitive?.doubleOrNull
        val actor = latest["actor"]?.jsonPrimitive?.contentOrNull
        Incident(name.replace('_', ' '), listOfNotNull(actor?.let { "Actor: $it" }, detail.takeIf { it.isNotBlank() }).joinToString(" · "),
            at?.let { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT).format(java.util.Date((it * 1000).toLong())) + " · device time" } ?: "Time unavailable",
            detail.contains("failed", true) || detail.contains("blocked", true))
    }
    state.snapshot?.let { ActivityScreen(it, events, if (state.administration && state.connected && !state.actionBusy) { process ->
        val tool = Tool("Stop ${process.name}", "Terminate process ${process.pid} on ${state.selected?.name}. Unsaved data may be lost.", "kill")
        model.review(tool, buildJsonObject { put("action", "kill"); put("pids", JsonArray(listOf(JsonPrimitive(process.pid)))) })
    } else null, processesOnly = processesOnly, onStopMany = if (state.administration && state.connected && !state.actionBusy) { processes ->
        val tool = Tool("End selected processes", "Terminate only the reviewed PIDs on ${state.selected?.name}. Unsaved work may be lost. Server protection rules still apply.", "kill")
        model.review(tool, buildJsonObject { put("action", "kill"); put("pids", JsonArray(processes.map { JsonPrimitive(it.pid) })) })
    } else null) }
    if (!processesOnly) state.documents["/api/usage"]?.let { usage ->
        var more by remember { mutableStateOf(false) }
        Section("Activity summary") {
            MetricRow("Events in returned history", usage.obj().count("events")?.toString() ?: "Unavailable")
            CossTextButton(onClick = { more = !more }) { Text(if (more) "Fewer options" else "More options") }
            if (more) ContextualDocument(Feature.Maintenance, "/api/usage", usage, {}, null)
        }
    }
}
