package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

internal fun validBackupSchedule(mode: String, value: String): Boolean {
    if (mode == "interval") return value.toIntOrNull() in 1..168
    if (mode !in setOf("daily", "times")) return false
    val times = value.split(',').map(String::trim)
    return times.size in 1..(if (mode == "daily") 1 else 24) && times.all { Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(it) }
}

/** Uses the existing setup/prepare/confirm API. Drafts never silently change server policy. */
@Composable internal fun BackupWorkspace(status: JsonElement?, setup: JsonElement?, canEdit: Boolean,
                                         onReview: (Tool, JsonObject) -> Unit, onEditSources: () -> Unit) {
    val details = backupDetails(status, setup)
    val schedule = setup.obj()?.get("backup").obj()?.get("schedule").obj()
    val modes = listOf("daily", "interval", "times")
    var mode by remember(setup) { mutableStateOf(schedule.text("mode") ?: "daily") }
    var value by remember(setup) { mutableStateOf(when (mode) {
        "interval" -> schedule.text("interval_hours").orEmpty()
        "times" -> (schedule?.get("times") as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.joinToString(", ")
        else -> schedule.text("time").orEmpty()
    }) }
    var enabled by remember(setup) { mutableStateOf(schedule.flag("enabled")) }
    var selectedSources by remember(setup) { mutableStateOf(details.sources.orEmpty().toSet()) }
    var inspected by remember { mutableStateOf<ArchiveDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val scheduleTool = ToolCatalog.tools(Feature.Backups).first { it.fixed["op"] == "schedule" }
    CossFrame("Backup policy", "Set when it runs. Review before applying changes.", footer = {
        Text("Changes use the server timezone. An exact next run is not reported.", color = Muted, style = MaterialTheme.typography.bodySmall)
        error?.let { Notice(it, true) }
        CossButton(onClick = {
            if (enabled == null || !validBackupSchedule(mode, value)) error = "Choose an enabled state and valid schedule: HH:MM, 1–168 hours, or up to 24 comma-separated HH:MM times."
            else { error = null; onReview(scheduleTool, scheduleTool.payload(mapOf("mode" to mode, "value" to value, "enabled" to enabled.toString()))) }
        }, enabled = canEdit && setup != null, modifier = Modifier.fillMaxWidth()) { Text("Review schedule changes") }
    }) {
        CossPanel {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("Automatic backups", style = MaterialTheme.typography.labelLarge)
                    Text(when (enabled) { true -> "Enabled"; false -> "Paused"; null -> "State unavailable" }, color = Muted, style = MaterialTheme.typography.bodySmall)
                }
                Switch(enabled == true, { enabled = it }, enabled = canEdit && setup != null)
            }
        }
        CossPanel {
            Text("Backup schedule", style = MaterialTheme.typography.labelLarge)
            if (canEdit) CossSegments(listOf("Daily", "Interval", "Times"), modes.indexOf(mode), { mode = modes[it]; value = "" }, Modifier.fillMaxWidth())
            else Text(details.schedule, color = Muted)
            CossField(if (mode == "interval") "Interval hours" else if (mode == "times") "Scheduled times" else "Scheduled time", value, { value = it },
                hint = if (mode == "interval") "1–168 hours" else "24-hour HH:MM · server time", enabled = canEdit)
            Text(details.scheduleNote, color = Muted, style = MaterialTheme.typography.bodySmall)
            HorizontalDivider(color = Rule)
            Text("Local retention", style = MaterialTheme.typography.labelLarge)
            Text(details.retention)
            Text("Retention limit only. ${details.archives?.size?.let { "$it local archives reported." } ?: "Archive count unavailable."} This server API cannot edit retention.", color = Muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    CossFrame("Source folders", "Manual backups use the saved server configuration.", footer = {
        CossOutlinedButton(onClick = {
            val tool = ToolCatalog.tools(Feature.Backups).first { it.fixed["op"] == "sources" }
            onReview(tool, tool.payload(mapOf("paths" to details.sources.orEmpty().filter { it in selectedSources }.joinToString("\n"))))
        }, enabled = canEdit && selectedSources.isNotEmpty() && selectedSources != details.sources.orEmpty().toSet(), modifier = Modifier.fillMaxWidth()) { Text("Review source changes") }
        CossOutlinedButton(onClick = onEditSources, enabled = canEdit, modifier = Modifier.fillMaxWidth()) { Text("Add or edit server folders") }
        CossButton(onClick = {
            val tool = ToolCatalog.tools(Feature.Backups).first { it.action == "backup_now" }; onReview(tool, tool.payload(emptyMap()))
        }, enabled = canEdit && !details.sources.isNullOrEmpty() && selectedSources == details.sources.toSet(), modifier = Modifier.fillMaxWidth()) { Text("Back up now") }
        Text("Unsaved selections do not change the folders backed up. Review and save source changes first.", color = Muted, style = MaterialTheme.typography.bodySmall)
    }) {
        CossPanel {
            if (details.sources.isNullOrEmpty()) Text(if (details.sources == null) "Source list unavailable." else "No source folders configured.", color = Muted)
            details.sources?.forEachIndexed { index, path ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(path in selectedSources, { checked -> selectedSources = if (checked) selectedSources + path else selectedSources - path }, enabled = canEdit, modifier = Modifier.testTag("backup-source-$index"))
                    Text(path, Modifier.weight(1f))
                }
            }
            Text("Sources & destination", style = MaterialTheme.typography.labelLarge)
            Text(details.remotes?.joinToString("\n")?.ifEmpty { "No cloud remotes configured" } ?: "Cloud destinations unavailable", color = Muted)
            Text(details.folder, color = Muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    CossFrame("Stored archives", details.archives?.let { "${it.size} local ${if (it.size == 1) "archive" else "archives"} reported · server returns up to 10" } ?: "Archive list unavailable") {
        CossPanel {
            if (details.archives?.isEmpty() == true) Text("No local archives were reported.", color = Muted)
            details.archives?.forEachIndexed { index, archive ->
                if (index > 0) HorizontalDivider(color = Rule)
                Column(Modifier.fillMaxWidth().clickable { inspected = archive }.padding(vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(archive.name, style = MaterialTheme.typography.labelLarge)
                    DetailFields(listOf(DetailField("Archive size", archive.size), DetailField("Archive last modified", archive.modified)))
                    Text("Inspect archive details", color = Muted, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
    CossFrame("Latest backup result", "Latest-run file count is separate from stored archive count.") {
        CossPanel {
            Text(details.result, style = MaterialTheme.typography.titleMedium)
            MetricRow("Files processed in the latest run", details.files)
            Text(details.resultNote, color = Muted, style = MaterialTheme.typography.bodySmall)
            MetricRow("Backup activity", details.activity); MetricRow("Backup engine", details.engine)
        }
    }
    inspected?.let { archive -> CossDialog(onDismissRequest = { inspected = null }, title = { Text(archive.name) }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            DetailFields(listOf(DetailField("Archive size", archive.size), DetailField("Archive last modified", archive.modified)))
            Text("Compressed archive metadata. The latest-run file count does not prove this archive's contents.", color = Muted)
        }
    }, confirmButton = { CossTextButton(onClick = { inspected = null }) { Text("Done") } }) }
}
