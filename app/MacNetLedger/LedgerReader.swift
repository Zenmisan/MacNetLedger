import Foundation
import SQLite3

/// Model structures for MacNetLedger telemetry
public struct LiveSummary {
    public let rxRate: Double
    public let txRate: Double
    public let topProcess: String
    public let topCategory: String
    public let networkName: String
    public let isHotspot: Bool
    public let hotspotTodayBytes: Int64
}

public struct ProcessGroupItem: Identifiable {
    public let id = UUID()
    public let rootGroup: String
    public let category: String
    public let totalRx: Int64
    public let totalTx: Int64
    public let totalBytes: Int64
    public let children: [ProcessChildItem]
}

public struct ProcessChildItem: Identifiable {
    public let id = UUID()
    public let childComm: String
    public let childDetail: String
    public let rxBytes: Int64
    public let txBytes: Int64
    public let totalBytes: Int64
}

public struct HistogramBucket: Identifiable {
    public let id = UUID()
    public let timestamp: Int64
    public let rxBytes: Int64
    public let txBytes: Int64
    public let totalBytes: Int64
}

/// Reads from /Library/Application Support/MacNetLedger/ledger.db in WAL read-only mode
public class LedgerReader {
    private var db: OpaquePointer?
    private let dbPath: String

    public init(dbPath: String = "/Library/Application Support/MacNetLedger/ledger.db") {
        self.dbPath = dbPath
        _ = ensureDatabaseOpen()
    }

    deinit {
        if let db = db {
            sqlite3_close(db)
        }
    }

    @discardableResult
    private func ensureDatabaseOpen() -> Bool {
        if db != nil { return true }
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        if sqlite3_open_v2(dbPath, &db, flags, nil) == SQLITE_OK {
            var statement: OpaquePointer?
            sqlite3_prepare_v2(db, "PRAGMA query_only = ON;", -1, &statement, nil)
            sqlite3_step(statement)
            sqlite3_finalize(statement)
            return true
        }
        return false
    }

    public func fetchLiveSummary() -> LiveSummary? {
        guard ensureDatabaseOpen(), let db = db else { return nil }
        let sql = """
            SELECT rx_rate, tx_rate, top_process, top_category, network_name, is_hotspot, hotspot_today_bytes
            FROM live_summary WHERE id = 1;
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }

        if sqlite3_step(stmt) == SQLITE_ROW {
            let rxRate = sqlite3_column_double(stmt, 0)
            let txRate = sqlite3_column_double(stmt, 1)
            let topProc = String(cString: sqlite3_column_text(stmt, 2))
            let topCat = String(cString: sqlite3_column_text(stmt, 3))
            let netName = String(cString: sqlite3_column_text(stmt, 4))
            let isHs = sqlite3_column_int(stmt, 5) != 0
            let hsToday = sqlite3_column_int64(stmt, 6)

            return LiveSummary(
                rxRate: rxRate,
                txRate: txRate,
                topProcess: topProc,
                topCategory: topCat,
                networkName: netName,
                isHotspot: isHs,
                hotspotTodayBytes: hsToday
            )
        }
        return nil
    }

    public func fetchProcessGroups(startTs: Int64, endTs: Int64, hotspotOnly: Bool = false) -> [ProcessGroupItem] {
        guard ensureDatabaseOpen(), let db = db else { return [] }
        let table = (endTs - startTs) > (48 * 3600) ? "rollup_1hour" : "rollup_5min"
        var sql = """
            SELECT root_group, category, child_comm, child_detail, SUM(rx_bytes), SUM(tx_bytes)
            FROM \(table)
            WHERE bucket_ts BETWEEN ? AND ?
        """
        if hotspotOnly {
            sql += " AND is_hotspot = 1 "
        }
        sql += " GROUP BY root_group, child_comm, child_detail ORDER BY SUM(rx_bytes + tx_bytes) DESC;"

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int64(stmt, 1, startTs)
        sqlite3_bind_int64(stmt, 2, endTs)

        var groupMap: [String: (category: String, rx: Int64, tx: Int64, children: [ProcessChildItem])] = [:]

        while sqlite3_step(stmt) == SQLITE_ROW {
            let root = String(cString: sqlite3_column_text(stmt, 0))
            let cat = String(cString: sqlite3_column_text(stmt, 1))
            let comm = String(cString: sqlite3_column_text(stmt, 2))
            let detail = String(cString: sqlite3_column_text(stmt, 3))
            let rx = sqlite3_column_int64(stmt, 4)
            let tx = sqlite3_column_int64(stmt, 5)

            let child = ProcessChildItem(
                childComm: comm,
                childDetail: detail,
                rxBytes: rx,
                txBytes: tx,
                totalBytes: rx + tx
            )

            if var existing = groupMap[root] {
                existing.rx += rx
                existing.tx += tx
                existing.children.append(child)
                groupMap[root] = existing
            } else {
                groupMap[root] = (category: cat, rx: rx, tx: tx, children: [child])
            }
        }

        return groupMap.map { root, val in
            ProcessGroupItem(
                rootGroup: root,
                category: val.category,
                totalRx: val.rx,
                totalTx: val.tx,
                totalBytes: val.rx + val.tx,
                children: val.children
            )
        }.sorted { $0.totalBytes > $1.totalBytes }
    }
}
