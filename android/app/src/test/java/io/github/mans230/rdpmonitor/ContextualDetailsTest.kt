package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.data.DemoDocuments
import io.github.mans230.rdpmonitor.feature.more.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ContextualDetailsTest {
    private fun json(value: String) = Json.parseToJsonElement(value)
    @Test fun latestFilesStoredArchivesAndRetentionAreDifferentFacts() {
        val details = backupDetails(DemoDocuments.at("/api/backup"), DemoDocuments.at("/api/setup"))
        assertEquals("42", details.files)
        assertEquals(1, details.archives!!.size)
        assertEquals("Up to 3 local copies", details.retention)
        assertEquals("500 MiB", details.archives.single().size)
        assertFalse(details.archives.single().raw.containsKey("files"))
        assertEquals("Verified", details.result)
        assertEquals("No job running", details.activity)
        assertTrue(details.archives.single().modified.endsWith("device time"))
        assertEquals("Every day at 03:00", details.schedule)
        assertFalse(details.schedule.contains("Tomorrow"))
        assertEquals(2, details.sources!!.size); assertEquals(1, details.remotes!!.size)
    }
    @Test fun zerosUnknownsAndIncompleteResponsesStayDistinct() {
        val empty = backupDetails(null, null)
        assertNull(empty.archives); assertEquals("Unavailable", empty.files); assertEquals("Unavailable", empty.retention)
        val zero = backupDetails(json("""{"last":{"files":0},"items":[],"settings":{"keep_local_copies":-1}}"""), null)
        assertEquals("0", zero.files); assertTrue(zero.archives!!.isEmpty()); assertEquals("Unavailable", zero.retention)
        assertEquals("0 bytes", detailBytes(0)); assertEquals("1 byte", detailBytes(1)); assertEquals("1 KiB", detailBytes(1024))
        assertEquals("Unavailable", detailBytes(-1))
        assertNull(backupDetails(json("""{"items":[1]}"""), null).archives)
        val invalid = schemaCards(Feature.LocalUsers, "/api/users", json("""{"items":["unexpected"]}"""))!!.first()
        assertEquals("Unavailable", invalid.fields.single().value)
    }
    @Test fun conflictingAndHistoricalResultsNeverBecomeVerificationProof() {
        val conflict = backupDetails(json("""{"last":{"state":"verified","verified":false}}"""), null)
        assertEquals("Conflicting verification status", conflict.result)
        val recorded = backupDetails(json("""{"last":{"last_success":"2026-11-25T03:00:00","last_attempt":"2026-11-26T03:00:00"}}"""), null)
        assertEquals("Latest result not reported", recorded.result)
        assertTrue(recorded.resultNote.contains("server-reported time"))
        val completed = backupDetails(json("""{"last":{"status":"ok"}}"""), null)
        assertEquals("Completed · verification not reported", completed.result)
    }
    @Test fun scheduleUsesDeclaredModeAndReportsConflictingSources() {
        val status = json("""{"settings":{"schedule_enabled":false,"schedule_time":"01:00"}}""")
        val setup = json("""{"backup":{"schedule":{"enabled":true,"mode":"interval","interval_hours":10},"timezone":"Server zone"}}""")
        val details = backupDetails(status, setup)
        assertEquals("Every 10 hours", details.schedule); assertEquals("Conflicting settings", details.scheduleState)
        assertTrue(details.scheduleNote.contains("disagree"))
        assertTrue(backupDetails(status, null).schedule.contains("schedule mode unavailable"))
    }
    @Test fun portMemoryDurationAndSessionDatesUseTheirOwnSchemas() {
        val rdp = schemaCards(Feature.RdpAccess, "/api/rdp", DemoDocuments.at("/api/rdp"))!!.first()
        assertEquals("3389", rdp.fields.first { it.label == "Configured TCP port" }.value)
        val info = schemaCards(Feature.SystemTools, "/api/sysinfo", DemoDocuments.at("/api/sysinfo"))!!.first()
        assertEquals("12 GiB", info.fields.first { it.label == "Installed memory" }.value)
        assertEquals("1d 0h 0m", info.fields.first { it.label == "Host uptime" }.value)
        val session = schemaCards(Feature.Access, "/api/mobile/v1/sessions", DemoDocuments.at("/api/mobile/v1/sessions"))!![1]
        assertTrue(session.fields.first { it.label == "App session created" }.value.endsWith("device time"))
        val users = schemaCards(Feature.LocalUsers, "/api/users", json("""{"items":[{"name":"fixture","enabled":true,"last":"/Date(1795650000000)/"}]}"""))!![1]
        assertTrue(users.fields.first { it.label == "Last sign-in reported by Windows" }.value.endsWith("device time"))
    }
    @Test fun rawUnknownCountsStayRawAndSecretsAreRemovedRecursively() {
        val safe = redactedDetails(json("""{"count":5000000000,"worker":{"token":"secret","password":"secret","state":"idle"},"items":[{"secret_access_key":"secret","size":524288000}]}""")).toString()
        assertTrue(safe.contains("5000000000")); assertTrue(safe.contains("524288000")); assertFalse(safe.contains("secret")); assertTrue(safe.contains("idle"))
        val metadata = redactedDetails(json("""{"question":{"secret":true,"default":"hidden-default"},"setting":{"key":"api_password","value":"hidden-value"}}""")).toString()
        assertFalse(metadata.contains("hidden-default")); assertFalse(metadata.contains("hidden-value"))
    }
    @Test fun automationChoicesMatchServerSupportedListsAndTrapNamesAreNotAccounts() {
        val tool = ToolCatalog.tools(Feature.Automation).single()
        assertEquals(listOf("watch", "keepalive", "svcwatch"), tool.fields.first { it.key == "list" }.options)
        assertTrue(ToolCatalog.documents(Feature.Automation).any { it.second.endsWith("list=svcwatch") })
        val traps = schemaCards(Feature.Protection, "/api/traps", json("""{"items":["trap-one","trap-two"]}"""))!!.single()
        assertEquals("2", traps.fields.first().value)
        assertTrue(traps.fields.any { it.value == "trap-two" })
        assertTrue(traps.note!!.contains("not an inventory"))
    }
}
