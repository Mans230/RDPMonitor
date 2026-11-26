package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.data.DemoDocuments
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class UxRegressionTest {
    @Test fun rootBackDoesNotTrapUsersInTheServerChooser() {
        assertEquals(RootBack.System, rootBack(false, Destination.Overview))
        assertEquals(RootBack.Overview, rootBack(false, Destination.More))
        assertEquals(RootBack.Tools, rootBack(true, Destination.More))
    }
    @Test fun expiredSessionKeepsHistoryButDisablesManagementAndMarksStale() {
        val live = AppState(snapshot = io.github.mans230.rdpmonitor.data.DemoData.snapshot(), connected = true, administration = true)
        val ended = live.sessionEnded()
        assertFalse(ended.connected); assertFalse(ended.administration); assertTrue(ended.readingsStale)
        assertSame(live.snapshot, ended.snapshot); assertTrue(ended.message!!.contains("Sign in again"))
    }
    @Test fun permissionsAndHumanValuesDescribeTheirMeaning() {
        assertEquals("Administration", scopeTitle("administration"))
        assertEquals("Monitoring only", scopeTitle("monitoring:read"))
        assertEquals("Healthy", readableValue("healthy", JsonPrimitive(true)))
        assertEquals("Not installed", readableValue("installed", JsonPrimitive(false)))
        assertEquals("No", readableValue("panic", JsonPrimitive(false)))
        assertEquals("Enabled", readableValue("enabled", JsonPrimitive(true)))
        assertEquals("50.0 GiB", readableValue("size", JsonPrimitive(53687091200L)))
        assertFalse(readableValue("modified", JsonPrimitive(1795650000)).contains("1795650000"))
    }
    @Test fun setupSectionsOnlyShowRelevantInformation() {
        val setup = DemoDocuments.at("/api/setup")
        val backup = sectionDocument(Feature.Backups, "/api/setup", setup).jsonObject
        assertTrue(backup.containsKey("backup")); assertFalse(backup.containsKey("images")); assertFalse(backup.containsKey("remote"))
        val cloud = sectionDocument(Feature.Cloud, "/api/setup", setup).jsonObject
        assertTrue(cloud.containsKey("images")); assertFalse(cloud.containsKey("backup")); assertFalse(cloud.containsKey("remote"))
        val access = sectionDocument(Feature.Access, "/api/setup", setup).jsonObject
        assertEquals("Passkey", access["authentication"]!!.jsonPrimitive.content)
    }
    @Test fun dangerousChoicesRequireDeliberateSelection() {
        val panic = ToolCatalog.tools(Feature.Protection).first { it.fixed["op"] == "panic" }
        assertTrue(panic.dangerous)
        assertTrue(runCatching { panic.payload(mapOf("mode" to "")) }.isFailure)
        assertEquals("off", panic.payload(mapOf("mode" to "off"))["mode"]!!.jsonPrimitive.content)
        val user = ToolCatalog.tools(Feature.RdpAccess).first { it.action == "user" }
        assertTrue(runCatching { user.payload(mapOf("name" to "example", "op" to "")) }.isFailure)
    }
    @Test fun diagnosticHintsMatchServerParameterRules() {
        assertTrue(diagnosticRequiresArgument("ps"))
        assertTrue(diagnosticHint("ps").contains("process name", ignoreCase = true))
        assertFalse(diagnosticHint("ps").contains("Leave parameters empty"))
        assertTrue(diagnosticRequiresArgument("nettest"))
        assertFalse(diagnosticRequiresArgument("bigfiles"))
        assertFalse(diagnosticHint("bigfiles").contains("folder", ignoreCase = true))
        assertTrue(diagnosticHint("bigfiles").contains("system drive", ignoreCase = true))
        assertTrue(diagnosticHint("bigfiles").contains("ignored", ignoreCase = true))
        assertFalse(diagnosticHint("logins").contains("number of days", ignoreCase = true))
        assertTrue(diagnosticHint("logins").contains("3 days"))
        assertFalse(diagnosticRequiresArgument("diagnose"))
        assertFalse(diagnosticRequiresArgument("speedtest"))
        assertTrue(diagnosticHint("speedtest").contains("No parameters are needed"))
    }
    @Test fun demoCoversEveryManagementSectionWithSampleData() {
        Feature.entries.forEach { feature -> ToolCatalog.documents(feature).forEach { (_, path) ->
            assertNotEquals(JsonNull, sectionDocument(feature, path, DemoDocuments.at(path)))
        } }
    }
}
