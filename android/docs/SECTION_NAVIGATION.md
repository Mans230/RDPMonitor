# Standalone section pages (0.6.2)

Every selected function replaces Overview in the content viewport. The bottom navigation is outside the scrolling list; Scaffold reserves its height so the final control stays reachable. Each route begins at its own page title, and switching sections resets the route scroll position. Back from a function returns to All sections, then Overview. Connector selection preserves the existing session behavior.

Overview contains only the CPU, memory and storage summaries plus uptime and latest backup health. Functions live on their selected pages. Server status shows uptime from /api/sysinfo uptime_s and the latest backup result from /api/backup, using the existing contextual backup interpreter. These administrative responses load on entering Overview and on Refresh; no frequent sysinfo polling, local duration estimate, invented success or privilege upgrade is introduced. Monitoring-only sessions explicitly report the approval requirement. The server API and authentication are unchanged.

Native journey checks cover all function pages, navigation from a deeply scrolled page, visible destination titles without an Overview prefix, More/Bandwidth/back behavior, server status labels and duration validation. Phone/tablet screenshots and the offline action gates remain part of the full Android check suite.
