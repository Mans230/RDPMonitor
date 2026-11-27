package io.github.mans230.rdpmonitor.feature.activity

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

internal fun processIdentity(row: ProcessRow) = "${row.pid}:${row.name}"
internal fun matchingProcesses(rows: List<ProcessRow>, query: String, high: Boolean) = rows.filter {
    (it.name.contains(query.trim(), true) || it.pid.toString().contains(query.trim())) && (!high || (it.cpu ?: -1.0) >= 5.0)
}

@Composable fun ProcessWorkspace(snapshot: Snapshot, onStop: ((ProcessRow) -> Unit)?, onStopMany: ((List<ProcessRow>) -> Unit)? = null) {
    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableIntStateOf(0) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var inspected by remember { mutableStateOf<ProcessRow?>(null) }
    val rows = matchingProcesses(snapshot.processes, query, filter == 1)
    val current = snapshot.processes.filter { processIdentity(it) in selected && it.pid > 4 }
    LaunchedEffect(snapshot.processes) { selected = selected.intersect(snapshot.processes.map(::processIdentity).toSet()) }
    CossFrame("Process readings", "Current server sample; the list may be bounded by the server.") {
        CossPanel { MetricRow("Server CPU", percent(snapshot.cpu)); MetricRow("Reported processes", snapshot.processes.size.toString()) }
    }
    CossFrame("Running processes", "Select up to 50 exact PIDs to review an end action.", footer = {
        Text("${rows.size} shown · ${current.size} selected", color = Muted, style = MaterialTheme.typography.bodySmall)
        CossOutlinedButton(onClick = { onStopMany?.invoke(current) }, enabled = current.size in 1..50 && onStopMany != null,
            modifier = Modifier.fillMaxWidth()) { Text("Review end action") }
        if (onStopMany == null) Text("Administration access required to end processes.", color = Muted, style = MaterialTheme.typography.bodySmall)
    }) {
        CossPanel {
            CossField("Search process name or PID", query, { query = it; selected = emptySet() })
            CossSegments(listOf("All ${snapshot.processes.size}", "CPU ≥ 5%"), filter, { filter = it; selected = emptySet() }, Modifier.fillMaxWidth())
        }
        CossPanel {
            if (rows.isEmpty()) {
                Text(if (snapshot.processes.isEmpty()) "No process readings received." else "No matching processes.", color = Muted)
                CossTextButton(onClick = { query = ""; filter = 0; selected = emptySet() }) { Text("Clear filters") }
            }
            val listHeight = (LocalConfiguration.current.screenHeightDp * .40f).dp.coerceIn(220.dp, 360.dp)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = listHeight).testTag("process-list")) {
            itemsIndexed(rows, key = { _, row -> processIdentity(row) }) { index, row ->
                if (index > 0) HorizontalDivider(color = Rule)
                BoxWithConstraints(Modifier.fillMaxWidth()) {
                    val compact = maxWidth < 340.dp
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = processIdentity(row) in selected, enabled = row.pid > 4 && (processIdentity(row) in selected || current.size < 50),
                            onCheckedChange = { checked -> selected = if (checked) selected + processIdentity(row) else selected - processIdentity(row) },
                            modifier = Modifier.testTag("select-process-${row.pid}").semantics { contentDescription = "Select ${row.name}, PID ${row.pid}" })
                        Column(Modifier.weight(1f).clickable { inspected = row }.padding(vertical = 8.dp).testTag("process-${row.pid}"), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                            Text(row.name, style = MaterialTheme.typography.bodyMedium)
                            Text("PID ${row.pid}", color = Muted, style = MaterialTheme.typography.bodySmall)
                            if (compact) Text("CPU ${percent(row.cpu)} · ${bytes(row.memoryBytes)}", color = Muted, style = MaterialTheme.typography.bodySmall)
                            if (row.pid <= 4) Text("Core system process", color = Muted, style = MaterialTheme.typography.bodySmall)
                        }
                        if (!compact) {
                            Text(percent(row.cpu), Modifier.width(64.dp), style = ReadingStyle.merge(MaterialTheme.typography.bodySmall), textAlign = TextAlign.End)
                            Text(bytes(row.memoryBytes), Modifier.width(82.dp), style = ReadingStyle.merge(MaterialTheme.typography.bodySmall), textAlign = TextAlign.End)
                        }
                    }
                }
            }
            }
        }
    }
    Text("CPU is a share of server capacity. Memory is the working set in binary units. Changes are rechecked by the server.", color = Muted, style = MaterialTheme.typography.bodySmall)
    inspected?.let { row ->
        val stillReported = snapshot.processes.any { processIdentity(it) == processIdentity(row) }
        CossDialog(onDismissRequest = { inspected = null }, title = { Text(row.name) }, text = {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("Snapshot process details", color = Muted)
                MetricRow("Process ID", row.pid.toString()); MetricRow("CPU", percent(row.cpu)); MetricRow("Working memory", bytes(row.memoryBytes))
                if (!stillReported) Text("This process is no longer in the current sample. Refresh before reviewing a change.")
                CossOutlinedButton(onClick = { inspected = null; onStop?.invoke(row) }, enabled = row.pid > 4 && stillReported && onStop != null) { Text("Review stop PID ${row.pid}") }
            }
        }, confirmButton = { CossOutlinedButton(onClick = { inspected = null }, modifier = Modifier.fillMaxWidth()) { Text("Done") } })
    }
}
