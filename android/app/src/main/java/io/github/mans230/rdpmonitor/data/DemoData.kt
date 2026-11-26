package io.github.mans230.rdpmonitor.data

import io.github.mans230.rdpmonitor.core.model.*

/** Deliberate offline fixture. Never mixed with real server observations. */
object DemoData {
    private const val GiB = 1_073_741_824L
    val incidents = listOf(
        Incident("Memory back to normal", "Recovered to 49%. One incident, no repeated notifications.", "8 min ago"),
        Incident("Backup verified", "Local archive completed and passed verification.", "03:00"),
        Incident("New device approval", "A registered device is waiting for the owner in Telegram.", "3 min ago", true)
    )
    val traffic = Traffic(listOf(6, 4, 8, 5, 9, 3, 7, 8, 4, 10, 6, 4, 7, 3).mapIndexed { i, gb ->
        val total = gb * GiB
        TrafficDay("${i + 1}", total * 4 / 5, total - total * 4 / 5)
    }, 500 * GiB)
    fun snapshot(now: Long = System.currentTimeMillis()) = Snapshot(
        host = "Preview Windows server", cpu = 8.5, ram = 49.0, ramUsed = (12 * GiB * .49).toLong(), ramTotal = 12 * GiB,
        downloadBps = 150_000.0, uploadBps = 37_500.0, sessions = 1,
        disks = listOf(DiskRow("C:\\", 34.0, 132 * GiB)),
        processes = listOf(ProcessRow(3320, "pythonw.exe", 2.3, 87L * 1_048_576),
            ProcessRow(560, "svchost.exe", 1.1, 123L * 1_048_576), ProcessRow(3180, "explorer.exe", .6, 67L * 1_048_576)),
        history = List(31) { i -> ResourcePoint((30 - i) * 60,
            listOf(5.0, 7.0, 4.0, 12.0, 9.0, 6.0, 15.0, 8.5)[i % 8],
            if (i == 12 || i == 13) null else 46.0 + (i % 6)) }, capturedAt = now,
        cores = 8, remoteSessions = listOf(RemoteSession("demo-user", "rdp-tcp#1", "2", "active"))
    )
}
