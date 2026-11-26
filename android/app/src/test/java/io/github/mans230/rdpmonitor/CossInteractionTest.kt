package io.github.mans230.rdpmonitor

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import io.github.mans230.rdpmonitor.core.model.ProcessRow
import io.github.mans230.rdpmonitor.data.*
import io.github.mans230.rdpmonitor.feature.activity.*
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class CossInteractionTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    @Test fun processSelectionAndDetailsKeepExactPidAndFiltersClearHiddenSelections() {
        val rows = listOf(ProcessRow(17, "worker.exe", 12.0, 1048576), ProcessRow(18, "worker.exe", 0.0, 2097152), ProcessRow(4, "System", 1.0, 0))
        var reviewed = emptyList<ProcessRow>()
        ui.setContent { RdpTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            ProcessWorkspace(DemoData.snapshot().copy(processes = rows), {}, { reviewed = it })
        } } }
        ui.onNodeWithTag("select-process-4").performScrollTo().assertIsNotEnabled()
        ui.onNodeWithTag("select-process-18").performScrollTo().performClick()
        ui.onNodeWithText("Review end action").performScrollTo().performClick()
        ui.runOnIdle { assertEquals(listOf(18), reviewed.map { it.pid }) }
        ui.onNodeWithText("CPU ≥ 5%").performScrollTo().performClick()
        ui.onNodeWithTag("process-18").assertDoesNotExist()
        ui.onNodeWithText("Review end action").performScrollTo().assertIsNotEnabled()
        ui.onNodeWithTag("process-17").performScrollTo().performClick()
        ui.onNodeWithText("Process ID").assertIsDisplayed()
        ui.onNodeWithText("17").assertIsDisplayed()
        ui.onNodeWithText("Done").performClick()
    }
    @Test fun backupControlsReviewOnlyTheSupportedScheduleAndSavedSourceChanges() {
        var payload: JsonObject? = null
        ui.setContent { RdpTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            BackupWorkspace(DemoDocuments.at("/api/backup"), DemoDocuments.at("/api/setup"), true, { _, body -> payload = body }, {})
        } } }
        ui.onNodeWithText("Review schedule changes").performScrollTo().performClick()
        ui.runOnIdle {
            assertEquals("setup", payload!!["action"]!!.jsonPrimitive.content)
            assertEquals("schedule", payload!!["op"]!!.jsonPrimitive.content)
            assertEquals("03:00", payload!!["value"]!!.jsonPrimitive.content)
            assertNull(payload!!["keep_local_copies"])
        }
        ui.onNodeWithText("Up to 3 local copies").performScrollTo().assertIsDisplayed()
        ui.onNodeWithText("Back up now").performScrollTo().assertIsEnabled()
        ui.onNodeWithTag("backup-source-0").performScrollTo().performClick()
        ui.onNodeWithText("Back up now").performScrollTo().assertIsNotEnabled()
        ui.onNodeWithText("Review source changes").performScrollTo().performClick()
        ui.runOnIdle { assertEquals("sources", payload!!["op"]!!.jsonPrimitive.content); assertEquals(1, payload!!["paths"]!!.jsonArray.size) }
    }
    @Test fun scheduleValidationMatchesServerModesAndBounds() {
        assertTrue(validBackupSchedule("daily", "03:00")); assertFalse(validBackupSchedule("daily", "25:00"))
        assertTrue(validBackupSchedule("interval", "168")); assertFalse(validBackupSchedule("interval", "169"))
        assertFalse(validBackupSchedule("daily", "03:00,04:00")); assertTrue(validBackupSchedule("times", "03:00,04:00"))
        assertFalse(validBackupSchedule("interval", "1.5")); assertFalse(validBackupSchedule("unknown", "03:00"))
        assertFalse(validBackupSchedule("times", List(25) { "03:00" }.joinToString(",")))
    }
}
