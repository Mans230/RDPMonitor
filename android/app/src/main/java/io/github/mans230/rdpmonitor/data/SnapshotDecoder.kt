package io.github.mans230.rdpmonitor.data

import io.github.mans230.rdpmonitor.core.model.*
import kotlinx.serialization.json.*

object SnapshotDecoder {
    private fun JsonObject.number(key: String) = (get(key) as? JsonPrimitive)?.doubleOrNull?.takeIf(Double::isFinite)
    private fun JsonObject.objectAt(key: String) = get(key) as? JsonObject ?: JsonObject(emptyMap())
    private fun JsonObject.arrayAt(key: String) = get(key) as? JsonArray ?: JsonArray(emptyList())
    fun decode(input: String): Snapshot {
        val root = Json.parseToJsonElement(input).jsonObject
        require(root["hostname"] is JsonPrimitive && root["cpu"] is JsonObject && root["ram"] is JsonObject) { "Server returned incomplete monitoring data." }
        return Snapshot(
            root.getValue("hostname").jsonPrimitive.content,
            root.objectAt("cpu").number("pct"), root.objectAt("ram").number("pct"),
            root.objectAt("ram").number("used")?.toLong(), root.objectAt("ram").number("total")?.toLong(),
            root.number("down_bps"), root.number("up_bps"), (root["sessions"] as? JsonArray)?.size,
            root.arrayAt("disks").mapNotNull { it as? JsonObject }.map {
                DiskRow((it["mount"] ?: it["dev"])?.jsonPrimitive?.content ?: "Disk", it.number("pct"), it.number("free")?.toLong())
            }, root.arrayAt("procs").mapNotNull { it as? JsonObject }.map {
                ProcessRow(it.number("pid")?.toInt() ?: -1, it["name"]?.jsonPrimitive?.content ?: "Unavailable", it.number("cpu"), it.number("rss")?.toLong())
            }, emptyList(), root.number("ts")?.times(1000)?.toLong() ?: error("Server sample time is missing.")
        )
    }
}
