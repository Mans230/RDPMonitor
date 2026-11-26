package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.data.SnapshotDecoder
import io.github.mans230.rdpmonitor.feature.overview.backupLead
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class DashboardDataTest {
    private fun json(value: String) = Json.parseToJsonElement(value)
    @Test fun scheduleUsesServerTimezoneAndDoesNotInventTomorrowOrVerification() {
        val lead = backupLead(json("""{"backup":{"schedule":{"enabled":true,"mode":"daily","time":"03:15"},"timezone":"Pacific Standard Time"}}"""), json("""{"last":{"last_success":"2026-11-26T03:15:00","summary":"Success"}}"""))
        assertEquals("03:15", lead.value)
        assertTrue(lead.schedule.contains("Pacific Standard Time"))
        assertTrue(lead.schedule.contains("not reported"))
        assertFalse(lead.schedule.contains("Tomorrow"))
        assertTrue(lead.lastRun.contains("2026-11-26"))
        assertFalse(lead.lastRun.contains("verified"))
    }
    @Test fun emptyDisabledAndIntervalSchedulesStayDistinct() {
        assertEquals("Unavailable", backupLead(null, null).value)
        assertEquals("Not scheduled", backupLead(json("""{"backup":{"schedule":{"enabled":false,"time":"02:00"}}}"""), null).value)
        assertEquals("Every 6 hours", backupLead(json("""{"backup":{"schedule":{"enabled":true,"mode":"interval","interval_hours":6}}}"""), null).value)
        assertEquals("02:00, 18:00", backupLead(json("""{"backup":{"schedule":{"enabled":true,"mode":"times","times":["02:00","18:00"]}}}"""), null).value)
    }
    @Test fun successfulRunIsNotEnoughToClaimVerifiedIntegrity() {
        assertFalse(backupLead(null, json("""{"last":{"status":"ok"}}""")).lastRun.contains("verified"))
        assertEquals("Last archive not verified", backupLead(null, json("""{"last":{"status":"ok","verified":false}}""")).lastRun)
        assertEquals("Last archive verified · sample.zip", backupLead(null, json("""{"last":{"verified":true,"archive":"sample.zip"}}""")).lastRun)
    }
    @Test fun resourceAndSessionCardsUseRecordedDataWithoutMockFallback() {
        val snapshot = SnapshotDecoder.decode("""{"hostname":"actual-host","ts":100,"cpu":{"pct":0,"cores":8},"ram":{"pct":0},"disks":[{"mount":"D:\\","total":1000,"free":1000,"pct":0}],"sessions":[{"user":"operator","session":"rdp-tcp#3","id":"7","state":"Disc"}],"procs":[]}""")
        assertEquals("actual-host", snapshot.host); assertEquals(8, snapshot.cores)
        assertEquals(1000L, snapshot.disks.single().totalBytes)
        assertEquals(0.0, snapshot.disks.single().usedPercent!!, 0.0)
        assertEquals("operator", snapshot.remoteSessions.single().user)
        assertEquals("Disc", snapshot.remoteSessions.single().state)
        assertEquals("7", snapshot.remoteSessions.single().id)
        assertEquals(1, snapshot.sessions)
    }
}
