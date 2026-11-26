package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

private val detailsJson = Json { prettyPrint = true }

@Composable internal fun DetailFields(fields: List<DetailField>) {
    fields.forEach { field ->
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(field.label, color = Muted, style = MaterialTheme.typography.bodySmall)
            Text(field.value, style = MaterialTheme.typography.bodyLarge)
        }
    }
}
@Composable internal fun RawDetails(data: JsonElement, title: String = "Additional server details") {
    var expanded by remember { mutableStateOf(false) }
    var limit by remember { mutableIntStateOf(12000) }
    CossTextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Hide $title" else "Show $title") }
    if (expanded) {
        Text("Raw field names and values as reported by the server. Sensitive keys are hidden.", color = Muted, style = MaterialTheme.typography.bodySmall)
        val text = remember(data) { detailsJson.encodeToString(JsonElement.serializer(), redactedDetails(data)) }
        Text(text.take(limit), style = MaterialTheme.typography.bodySmall)
        if (limit < text.length) CossTextButton(onClick = { limit += 12000 }) { Text("Show more raw details") }
    }
}

@Composable internal fun RecordControls(record: JsonObject, openBrowser: (String) -> Unit, onTool: ((Tool, Map<String, String>) -> Unit)?) {
    // Keep the existing reviewed controls. Merely expanding details never mutates server state.
    if (record["id"] != null && record["scope"] != null && record["created"] != null && onTool != null) {
        val id = record.text("id") ?: return
        CossOutlinedButton(onClick = { onTool(Tool("Revoke app session", "Immediately end this app session. It must sign in again.", "mobile_revoke", mapOf("id" to id)), emptyMap()) }) { Text("Revoke app session") }
    }
    if (record["id"] != null && record["state"] != null && record["op"] != null) {
        listOf("url", "auth_url").forEach { key -> record.text(key)?.takeIf { it.startsWith("https://") }?.let { url -> CossTextButton(onClick = { openBrowser(url) }) { Text("Open cloud sign-in link") } } }
        val id = record.text("id") ?: return
        record.text("prompt")?.let { Text(it) }
        val question = record["question"].obj()
        val questionId = question.text("id") ?: record.text("question")
        if (onTool != null && questionId != null) {
            question.text("name")?.let { Text(it) }; question.text("help")?.let { Text(it, color = Muted) }
            question?.get("choices").rows().orEmpty().forEach { choice -> Text("${shown(choice.text("value"))} · ${shown(choice.text("label"))}", style = MaterialTheme.typography.bodySmall) }
            val kind = if (question.flag("secret") == false) "text" else "secret"
            CossOutlinedButton(onClick = { onTool(Tool("Answer cloud sign-in", "Send your answer to this pending server operation.", "setup", mapOf("op" to "answer", "job" to id, "question" to questionId, "value" to ""), listOf(ToolField("value", "Answer", kind, optional = question.flag("required") == false))), mapOf("value" to if (kind == "secret") "" else question.text("default").orEmpty())) }) { Text("Answer sign-in question") }
        }
        if (onTool != null && record.text("state") == "running") CossOutlinedButton(onClick = {
            onTool(Tool("Cancel cloud sign-in", "Cancel this pending setup operation.", "setup", mapOf("op" to "cancel", "job" to id)), emptyMap())
        }) { Text("Cancel operation") }
    }
}

@Composable internal fun ContextualDocument(feature: Feature, path: String, data: JsonElement, openBrowser: (String) -> Unit, onTool: ((Tool, Map<String, String>) -> Unit)?) {
    val cards = schemaCards(feature, path, data)
    if (cards == null) {
        // Settings already carry server-supplied labels and editable types; do not rename their keys.
        if (path == "/api/settings") {
            data.obj()?.get("groups").rows().orEmpty().forEach { group -> Section(shown(group.text("name"))) {
                (group["items"] as? JsonArray).orEmpty().forEach { NativeDocument(it, openBrowser, onTool) }
            } }
            RawDetails(data, "settings response details")
        } else if (path == "/api/docs") Section("Server command reference") { Text(shown(data.obj().text("markdown"))) }
        else Section("Server response") { Text("No contextual presentation is available for this response.", color = Muted); RawDetails(data, "unrecognized response details") }
        return
    }
    var visible by remember(path) { mutableIntStateOf(20) }
    cards.take(visible).forEach { card ->
        Section(card.title) {
            DetailFields(card.fields)
            card.note?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) }
            card.record?.let { RecordControls(it, openBrowser, onTool) }
        }
    }
    if (cards.size > visible) CossTextButton(onClick = { visible += 20 }) { Text("Show more · ${cards.size - visible} records remaining") }
    RawDetails(data)
}

@Composable internal fun BackupDetailsScreen(status: JsonElement?, setup: JsonElement?) {
    val details = backupDetails(status, setup)
    Section("Latest backup result", details.resultNote) {
        Text(details.result, style = MaterialTheme.typography.titleMedium)
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(details.files, style = ReadingStyle.copy(fontSize = 32.sp))
            Text("Files processed in the latest run", color = Muted, style = MaterialTheme.typography.bodySmall)
        }
        MetricRow("Backup activity", details.activity)
        MetricRow("Backup engine", details.engine)
    }
    Section("Stored archives", details.archives?.let { "${it.size} local ${if (it.size == 1) "archive" else "archives"} reported · server returns up to 10" } ?: "Archive list unavailable") {
        if (details.archives?.isEmpty() == true) Text("No local archives were reported.", color = Muted)
        details.archives?.forEach { archive ->
            Text(archive.name, style = MaterialTheme.typography.titleMedium)
            DetailFields(listOf(DetailField("Archive size", archive.size), DetailField("Archive last modified", archive.modified)))
            RawDetails(archive.raw, "archive details")
        }
    }
    Section("Backup schedule", details.scheduleNote) {
        DetailFields(listOf(DetailField("Schedule status", details.scheduleState), DetailField("Configured server schedule", details.schedule)))
    }
    Section("Local retention", "This is a retention limit, not a count of completed backups.") {
        DetailFields(listOf(DetailField("Retention limit", details.retention), DetailField("Local archives reported", details.archives?.size?.toString() ?: "Unavailable")))
    }
    Section("Sources & destination", "Configured cloud destinations do not prove a successful upload.") {
        DetailFields(listOf(DetailField("Folders to back up", details.sources?.size?.let { "$it ${if (it == 1) "folder" else "folders"} configured" } ?: "Unavailable")))
        details.sources?.forEach { Text(it) }
        DetailFields(listOf(DetailField("Configured backup cloud remotes", details.remotes?.size?.let { "$it configured ${if (it == 1) "remote" else "remotes"}" } ?: "Unavailable")))
        details.remotes?.forEach { Text(it) }
        DetailFields(listOf(DetailField("Backup cloud folder", details.folder)))
    }
}
