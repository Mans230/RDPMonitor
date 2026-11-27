package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
            question?.get("choices").rows().orEmpty().forEach { choice -> Text("${shown(choice.text("value"))} Â· ${shown(choice.text("label"))}", style = MaterialTheme.typography.bodySmall) }
            val kind = if (question.flag("secret") == false) "text" else "secret"
            CossOutlinedButton(onClick = { onTool(Tool("Answer cloud sign-in", "Send your answer to this pending server operation.", "setup", mapOf("op" to "answer", "job" to id, "question" to questionId, "value" to ""), listOf(ToolField("value", "Answer", kind, optional = question.flag("required") == false))), mapOf("value" to if (kind == "secret") "" else question.text("default").orEmpty())) }) { Text("Answer sign-in question") }
        }
        if (onTool != null && record.text("state") == "running") CossOutlinedButton(onClick = {
            onTool(Tool("Cancel cloud sign-in", "Cancel this pending setup operation.", "setup", mapOf("op" to "cancel", "job" to id)), emptyMap())
        }) { Text("Cancel operation") }
    }
}

@Composable internal fun ContextualDocument(feature: Feature, path: String, data: JsonElement, openBrowser: (String) -> Unit, onTool: ((Tool, Map<String, String>) -> Unit)?,
    cardFilter: (DetailCard) -> Boolean = { true }) {
    val cards = schemaCards(feature, path, data)?.filter(cardFilter)
    if (cards == null) {
        // Settings already carry server-supplied labels and editable types; do not rename their keys.
        if (path == "/api/settings") {
            data.obj()?.get("groups").rows().orEmpty().forEach { group ->
                Text(shown(group.text("name")), style = MaterialTheme.typography.titleMedium)
                (group["items"] as? JsonArray).orEmpty().forEach { NativeDocument(it, openBrowser, onTool) }
            }
        } else if (path == "/api/docs") Section("Server command reference") { Text(shown(data.obj().text("markdown"))) }
        else Section("Server response") { Text("Structured view unavailable. Open Report details in Diagnostics for the returned data.", color = Muted) }
        return
    }
    val render: @Composable (DetailCard) -> Unit = { card ->
        Column(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(card.title, style = MaterialTheme.typography.titleMedium)
            DetailFields(card.fields)
            card.note?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) }
            card.record?.let { RecordControls(it, openBrowser, onTool) }
        }
    }
    if (cards.size > 4) {
        render(cards.first())
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 340.dp)) { items(cards.drop(1)) { card -> render(card); HorizontalDivider(color = Rule) } }
    } else cards.forEach { render(it) }
}
