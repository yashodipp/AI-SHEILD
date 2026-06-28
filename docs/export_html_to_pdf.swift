import AppKit
import Foundation
import WebKit

let args = CommandLine.arguments

guard args.count == 3 else {
    fputs("Usage: swift export_html_to_pdf.swift <input-html> <output-pdf>\n", stderr)
    exit(1)
}

let inputURL = URL(fileURLWithPath: args[1])
let outputURL = URL(fileURLWithPath: args[2])

final class PDFExporter: NSObject, WKNavigationDelegate {
    private let webView: WKWebView
    private let outputURL: URL

    init(outputURL: URL) {
        self.outputURL = outputURL
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        self.webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 794, height: 1123), configuration: config)
        super.init()
        self.webView.navigationDelegate = self
    }

    func load(_ inputURL: URL) {
        let readAccessURL = inputURL.deletingLastPathComponent()
        webView.loadFileURL(inputURL, allowingReadAccessTo: readAccessURL)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            let config = WKPDFConfiguration()
            config.rect = webView.bounds
            webView.createPDF(configuration: config) { result in
                switch result {
                case .success(let data):
                    do {
                        try data.write(to: self.outputURL)
                        print("WROTE=\(self.outputURL.path)")
                        CFRunLoopStop(CFRunLoopGetMain())
                    } catch {
                        fputs("Failed to write PDF: \(error)\n", stderr)
                        exit(1)
                    }
                case .failure(let error):
                    fputs("Failed to create PDF: \(error)\n", stderr)
                    exit(1)
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fputs("Navigation failed: \(error)\n", stderr)
        exit(1)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fputs("Provisional navigation failed: \(error)\n", stderr)
        exit(1)
    }
}

let exporter = PDFExporter(outputURL: outputURL)
exporter.load(inputURL)
RunLoop.main.run()
