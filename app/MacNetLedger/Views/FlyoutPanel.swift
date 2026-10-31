import SwiftUI

public struct FlyoutPanelView: View {
    public let reader: LedgerReader

    @State private var selectedRange: String = "24H"
    @State private var filterHotspotOnly: Bool = false
    @State private var expandedGroups: Set<String> = []
    @State private var processGroups: [ProcessGroupItem] = []
    @State private var liveSummary: LiveSummary? = nil

    private let updateTimer = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()
    private let cyanColor = Color(red: 0.13, green: 0.83, blue: 0.93) // #22d3ee
    private let amberColor = Color(red: 0.96, green: 0.62, blue: 0.04) // #f59e0b
    private let bgColor = Color(red: 0.07, green: 0.09, blue: 0.11) // #12161C

    public init(reader: LedgerReader) {
        self.reader = reader
    }

    public var body: some View {
        VStack(spacing: 12) {
            // Header Bar
            HStack {
                Text("✦ MacNetLedger")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundColor(.white)

                Spacer()

                if let summary = liveSummary {
                    HStack(spacing: 6) {
                        Image(systemName: summary.isHotspot ? "antenna.radiowaves.left.and.right" : "wifi")
                            .font(.system(size: 11))
                        Text(summary.networkName.isEmpty ? "Connected" : summary.networkName)
                            .font(.system(size: 11, weight: .medium))
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(summary.isHotspot ? Color.pink.opacity(0.2) : Color.white.opacity(0.08))
                    .foregroundColor(summary.isHotspot ? .pink : .white)
                    .cornerRadius(6)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)

            // Segmented Presets & Filters
            HStack {
                HStack(spacing: 4) {
                    ForEach(["LIVE", "24H", "2D", "7D", "30D"], id: \.self) { preset in
                        Button(action: {
                            selectedRange = preset
                            refreshData()
                        }) {
                            Text(preset)
                                .font(.system(size: 10, weight: .semibold))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(selectedRange == preset ? cyanColor.opacity(0.25) : Color.white.opacity(0.05))
                                .foregroundColor(selectedRange == preset ? cyanColor : .gray)
                                .cornerRadius(4)
                        }
                        .buttonStyle(PlainButtonStyle())
                    }
                }

                Spacer()

                Button(action: {
                    filterHotspotOnly.toggle()
                    refreshData()
                }) {
                    HStack(spacing: 4) {
                        Image(systemName: filterHotspotOnly ? "checkmark.circle.fill" : "circle")
                        Text("Hotspot Only")
                    }
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(filterHotspotOnly ? .pink : .gray)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.white.opacity(0.05))
                    .cornerRadius(4)
                }
                .buttonStyle(PlainButtonStyle())
            }
            .padding(.horizontal, 16)

            // Summary Metrics Card
            let totalRx = processGroups.reduce(0) { $0 + $1.totalRx }
            let totalTx = processGroups.reduce(0) { $0 + $1.totalTx }
            let totalBytes = totalRx + totalTx

            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(selectedRange == "LIVE" ? "ACTIVE RATE" : "WINDOW TOTAL")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(.gray)
                    Text(selectedRange == "LIVE" && liveSummary != nil ?
                         formatRate((liveSummary?.rxRate ?? 0) + (liveSummary?.txRate ?? 0)) :
                         formatBytes(totalBytes))
                        .font(.system(size: 16, weight: .bold, design: .monospaced))
                        .foregroundColor(.white)
                }

                Spacer()

                HStack(spacing: 16) {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("⤓ DOWNLOAD")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundColor(cyanColor)
                        Text(selectedRange == "LIVE" && liveSummary != nil ?
                             formatRate(liveSummary?.rxRate ?? 0) :
                             formatBytes(totalRx))
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                            .foregroundColor(.white)
                    }

                    VStack(alignment: .trailing, spacing: 2) {
                        Text("⤒ UPLOAD")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundColor(amberColor)
                        Text(selectedRange == "LIVE" && liveSummary != nil ?
                             formatRate(liveSummary?.txRate ?? 0) :
                             formatBytes(totalTx))
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                            .foregroundColor(.white)
                    }
                }
            }
            .padding(12)
            .background(Color.white.opacity(0.04))
            .cornerRadius(8)
            .padding(.horizontal, 16)

            // Process Lineage Table or Empty State
            if processGroups.isEmpty {
                VStack(spacing: 12) {
                    Spacer()
                    Image(systemName: "waveform.path.ecg")
                        .font(.system(size: 32))
                        .foregroundColor(.gray.opacity(0.5))
                    Text("Recording network activity...")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.gray)
                    Text("Traffic will appear here as applications transfer data.")
                        .font(.system(size: 11))
                        .foregroundColor(.gray.opacity(0.7))
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let maxTotal = Double(processGroups.first?.totalBytes ?? 1)
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(processGroups) { group in
                            VStack(spacing: 4) {
                                // Top Parent Row
                                HStack {
                                    Button(action: {
                                        if expandedGroups.contains(group.rootGroup) {
                                            expandedGroups.remove(group.rootGroup)
                                        } else {
                                            expandedGroups.insert(group.rootGroup)
                                        }
                                    }) {
                                        HStack(spacing: 6) {
                                            Image(systemName: expandedGroups.contains(group.rootGroup) ? "chevron.down" : "chevron.right")
                                                .font(.system(size: 9))
                                                .foregroundColor(.gray)

                                            Text(group.rootGroup)
                                                .font(.system(size: 12, weight: .medium))
                                                .foregroundColor(.white)
                                                .lineLimit(1)
                                        }
                                    }
                                    .buttonStyle(PlainButtonStyle())

                                    Spacer()

                                    Text(selectedRange == "LIVE" ? formatRate(Double(group.totalBytes)) : formatBytes(group.totalBytes))
                                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                        .foregroundColor(.white)
                                }

                                // Dual-color Proportional Bar (Cyan Down / Amber Up)
                                GeometryReader { geo in
                                    let totalWidth = geo.size.width
                                    let groupRatio = CGFloat(Double(group.totalBytes) / max(1.0, maxTotal))
                                    let rowWidth = totalWidth * groupRatio
                                    let rxRatio = group.totalBytes > 0 ? CGFloat(Double(group.totalRx) / Double(group.totalBytes)) : 0.5
                                    let rxWidth = rowWidth * rxRatio
                                    let txWidth = rowWidth - rxWidth

                                    HStack(spacing: 0) {
                                        Rectangle().fill(cyanColor).frame(width: rxWidth)
                                        Rectangle().fill(amberColor).frame(width: txWidth)
                                        Spacer(minLength: 0)
                                    }
                                    .frame(height: 4)
                                    .background(Color.white.opacity(0.06))
                                    .cornerRadius(2)
                                }
                                .frame(height: 4)

                                // Expanded Children Lineage Tree
                                if expandedGroups.contains(group.rootGroup) {
                                    VStack(spacing: 4) {
                                        ForEach(group.children) { child in
                                            HStack {
                                                Text("└─ \(child.childComm)")
                                                    .font(.system(size: 10, design: .monospaced))
                                                    .foregroundColor(.gray)
                                                    .lineLimit(1)
                                                Spacer()
                                                Text(selectedRange == "LIVE" ? formatRate(Double(child.totalBytes)) : formatBytes(child.totalBytes))
                                                    .font(.system(size: 10, design: .monospaced))
                                                    .foregroundColor(.gray)
                                            }
                                            .padding(.leading, 18)
                                        }
                                    }
                                    .padding(.vertical, 2)
                                }
                            }
                            .padding(8)
                            .background(Color.white.opacity(0.025))
                            .cornerRadius(6)
                        }
                    }
                    .padding(.horizontal, 16)
                }
            }

            // Hotspot Daily Budget Warning Gauge
            if let summary = liveSummary, summary.isHotspot {
                let used = Double(summary.hotspotTodayBytes)
                let cap = 3.0 * 1024 * 1024 * 1024 // 3 GB
                let percent = min(1.0, used / cap)

                VStack(spacing: 4) {
                    HStack {
                        Text("Hotspot Daily Budget (3.0 GB)")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundColor(.pink)
                        Spacer()
                        Text("\(Int(percent * 100))% used")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundColor(.pink)
                    }

                    GeometryReader { geo in
                        HStack(spacing: 0) {
                            Rectangle()
                                .fill(percent > 0.85 ? Color.red : Color.pink)
                                .frame(width: geo.size.width * CGFloat(percent))
                            Spacer(minLength: 0)
                        }
                        .frame(height: 4)
                        .background(Color.white.opacity(0.08))
                        .cornerRadius(2)
                    }
                    .frame(height: 4)
                }
                .padding(10)
                .background(Color.pink.opacity(0.08))
                .cornerRadius(6)
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
        }
        .frame(width: 540, height: 640)
        .background(bgColor)
        .onAppear {
            refreshData()
        }
        .onReceive(updateTimer) { _ in
            refreshData()
        }
    }

    private func refreshData() {
        liveSummary = reader.fetchLiveSummary()
        if selectedRange == "LIVE" {
            processGroups = reader.fetchLiveProcessGroups()
            return
        }

        let now = Int64(Date().timeIntervalSince1970)
        let startTs: Int64
        switch selectedRange {
        case "24H": startTs = now - 86400
        case "2D": startTs = now - (2 * 86400)
        case "7D": startTs = now - (7 * 86400)
        case "30D": startTs = now - (30 * 86400)
        default: startTs = now - 86400
        }

        processGroups = reader.fetchProcessGroups(startTs: startTs, endTs: now, hotspotOnly: filterHotspotOnly)
    }

    private func formatRate(_ bytesPerSec: Double) -> String {
        if bytesPerSec >= 1048576 {
            return String(format: "%.1f MB/s", bytesPerSec / 1048576.0)
        } else if bytesPerSec >= 1024 {
            return String(format: "%.0f KB/s", bytesPerSec / 1024.0)
        } else {
            return String(format: "%.0f B/s", bytesPerSec)
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        if bytes >= 1073741824 {
            return String(format: "%.2f GB", Double(bytes) / 1073741824.0)
        } else if bytes >= 1048576 {
            return String(format: "%.1f MB", Double(bytes) / 1048576.0)
        } else if bytes >= 1024 {
            return String(format: "%.0f KB", Double(bytes) / 1024.0)
        } else {
            return "\(bytes) B"
        }
    }
}
