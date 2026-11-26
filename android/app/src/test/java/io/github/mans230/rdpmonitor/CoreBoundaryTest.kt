package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.core.security.*
import io.github.mans230.rdpmonitor.data.*
import org.junit.Assert.*
import org.junit.Test

class CoreBoundaryTest {
    @Test fun privateOriginNormalizesOnlyCanonicalPrivateHttps() {
        assertEquals("https://server.tail.ts.net", PrivateOrigin.parse(" https://SERVER.tail.ts.net:443/ "))
        listOf("http://server.tail.ts.net", "https://199.47.241.111:8399", "https://server.tail.ts.net.evil.test",
            "https://secret@server.tail.ts.net", "https://server.tail.ts.net/?token=secret",
            "https://server.tail.ts.net/panel", "https://server.tail.ts.net#secret", "https://server..ts.net",
            "https://server.tail.ts.net:8443", "https://localhost").forEach { value ->
            assertTrue("Must reject $value", runCatching { PrivateOrigin.parse(value) }.isFailure)
        }
    }
    @Test fun authorizationCannotSendTheUserToAnotherServer() {
        val origin = "https://server.tail.ts.net"
        assertEquals("$origin/mobile/authorize?request=abc", PrivateOrigin.sameServerUrl(origin, "$origin/mobile/authorize?request=abc"))
        listOf("https://another.tail.ts.net/auth", "http://server.tail.ts.net/auth", "https://server.tail.ts.net@evil.test/auth").forEach {
            assertTrue(runCatching { PrivateOrigin.sameServerUrl(origin, it) }.isFailure)
        }
    }
    @Test fun pkceMatchesRfc7636S256VectorAndGeneratesIndependentState() {
        assertEquals("0D29-9B1E", BrowserPairing.matchCode("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"))
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            BrowserPairing.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"))
        val a = BrowserPairing.create("profile", "https://server.tail.ts.net", 1000)
        val b = BrowserPairing.create("profile", "https://server.tail.ts.net", 1000)
        assertEquals(43, a.verifier.length); assertNotEquals(a.verifier, a.state); assertNotEquals(a.state, b.state)
    }
    @Test fun callbacksMustMatchStateHostExpiryAndUnambiguousParameters() {
        val pending = BrowserPairing.create("profile", "https://server.tail.ts.net", 1000)
        val code = "a".repeat(43)
        val good = "${BrowserPairing.REDIRECT}?state=${pending.state}&code=$code"
        assertEquals(code, BrowserPairing.callback(good, pending, 2000).code)
        listOf(good.replace(pending.state, "wrong"), good + "&state=duplicate", good + "&origin=https://evil.test",
            good.replace("auth/callback", "evil/callback"), good + "#fragment").forEach {
            assertTrue(runCatching { BrowserPairing.callback(it, pending, 2000) }.isFailure)
        }
        assertTrue(runCatching { BrowserPairing.callback(good, null, 2000) }.isFailure)
        assertTrue(runCatching { BrowserPairing.callback(good, pending, 601001) }.isFailure)
        assertTrue(runCatching { BrowserPairing.callback(good, pending, 999) }.isFailure)
    }
    @Test fun missingReadingsRemainMissingAndZerosRemainMeasuredZeros() {
        val result = SnapshotDecoder.decode("""{"hostname":"fixture","ts":10,"cpu":{"pct":0},"ram":{"pct":49,"total":12884901888},"down_bps":null,"up_bps":0,"sessions":[],"disks":[],"procs":[]}""")
        assertEquals(0.0, result.cpu!!, 0.0); assertNull(result.downloadBps); assertEquals(0.0, result.uploadBps!!, 0.0)
        assertNull(result.ramUsed); assertEquals(0, result.sessions); assertEquals(10000L, result.capturedAt)
        assertTrue(runCatching { SnapshotDecoder.decode("{}") }.isFailure)
    }
    @Test fun demoTrafficReconcilesFromDailyRowsAndHistoryHasGaps() {
        val traffic = DemoData.traffic
        assertEquals(84L * 1_073_741_824, traffic.totalBytes)
        assertEquals(traffic.totalBytes, traffic.downloadBytes + traffic.uploadBytes)
        assertEquals(.168, traffic.quotaFraction!!, .00001)
        val sample = DemoData.snapshot(1000)
        assertEquals(1000L, sample.capturedAt)
        assertTrue(sample.history.any { it.ram == null })
        assertTrue(sample.processes.none { it.pid == 0 || it.name.contains("Idle") })
    }
    @Test fun realHistoryFiltersFutureAndOldSamplesWithoutInventingReadings() {
        val snapshot = DemoData.snapshot(100_000)
        val updated = SnapshotDecoder.withHistory(snapshot, """{"points":[{"t":100,"c":0,"r":null},{"t":90,"c":null,"r":50},{"t":200,"c":99},{"t":-2000,"c":99}]}""")
        assertEquals(2, updated.history.size)
        assertEquals(10, updated.history.first().secondsAgo)
        assertNull(updated.history.first().cpu)
        assertEquals(0.0, updated.history.last().cpu!!, 0.0)
        assertNull(updated.history.last().ram)
        val gap = SnapshotDecoder.withHistory(snapshot, """{"points":[{"t":-100,"c":5},{"t":100,"c":5}]}""")
        assertTrue(gap.history.any { it.cpu == null && it.ram == null })
    }
}
