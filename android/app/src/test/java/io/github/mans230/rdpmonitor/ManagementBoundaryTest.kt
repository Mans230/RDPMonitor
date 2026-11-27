package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.data.SnapshotDecoder
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ManagementBoundaryTest {
    @Test fun storageFieldsStayWithTheirProviderAndCredentialsAreHiddenInReview() {
        val tool = ToolCatalog.tools(Feature.Cloud).first { it.title == "Create storage remote" }
        val body = tool.payload(mapOf("name" to "storage", "provider" to "sftp", "options.host" to "host.example",
            "options.user" to "admin", "options.pass" to "private-test-password", "options.secret_access_key" to "stale-other-provider-secret"))
        assertEquals("host.example", body["options"]!!.jsonObject["host"]!!.jsonPrimitive.content)
        assertFalse(body["options"]!!.jsonObject.containsKey("secret_access_key"))
        val review = tool.safeArguments(body).toString()
        assertFalse(review.contains("private-test-password")); assertTrue(review.contains("host.example"))
    }
    @Test fun processTargetsRejectSystemIdsAndMalformedValues() {
        val tool = ToolCatalog.tools(Feature.Commands).first { it.action == "kill" }
        listOf("", "0", "-1", "abc", "12,bad").forEach { value -> assertTrue(runCatching { tool.payload(mapOf("pids" to value)) }.isFailure) }
        assertEquals(listOf(22, 44), tool.payload(mapOf("pids" to "22,44"))["pids"]!!.jsonArray.map { it.jsonPrimitive.int })
    }
    @Test fun realBillingTotalsUseCycleOnlyWhileRetainingDailyHistory() {
        val traffic = SnapshotDecoder.traffic(Json.parseToJsonElement("""{"cycle_start":"2026-11-10","cycle_end":"2026-12-10","quota_bytes":1000,"days":[{"date":"2026-11-09","down":999,"up":0},{"date":"2026-11-10","down":100,"up":20},{"date":"2026-11-11","down":0,"up":10}]}"""))
        assertEquals(3, traffic.days.size); assertEquals(130L, traffic.totalBytes); assertEquals(.13, traffic.quotaFraction!!, .00001)
        assertEquals(30L, traffic.uploadBytes)
        assertTrue(runCatching { SnapshotDecoder.traffic(Json.parseToJsonElement("""{"days":[{"date":"2026-11-10","down":-1,"up":0}]}""")) }.isFailure)
    }
    @Test fun sectionsHaveDataOrContextualOperationsAndUpdateUsesSupportedApplyOperation() {
        Feature.entries.forEach { feature ->
            // These views consume the live Snapshot or the diagnostic request selected by the user.
            assertTrue(ToolCatalog.documents(feature).isNotEmpty() || feature in setOf(Feature.Processes, Feature.History, Feature.Diagnostics) ||
                feature == Feature.Maintenance && ToolCatalog.tools(feature).isNotEmpty())
        }
        // Operation history belongs to Activity; maintenance owns cleanup, logs/files and power.
        assertTrue(ToolCatalog.documents(Feature.Maintenance).isEmpty())
        val install = ToolCatalog.tools(Feature.Updates).first { it.title == "Install suite update" }
        assertEquals("apply", install.payload(emptyMap())["op"]!!.jsonPrimitive.content)
        val user = ToolCatalog.tools(Feature.RdpAccess).first { it.action == "user" }
        assertFalse(user.safeArguments(user.payload(mapOf("op" to "add", "name" to "fixture", "value" to "test-password"))).toString().contains("test-password"))
    }
}
