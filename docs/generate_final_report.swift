import AppKit
import Foundation
import WebKit

final class PDFRenderer: NSObject, WKNavigationDelegate {
    private let inputURL: URL
    private let outputURL: URL
    private let webView: WKWebView

    init(inputURL: URL, outputURL: URL) {
        self.inputURL = inputURL
        self.outputURL = outputURL
        self.webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 794, height: 1123))
        super.init()
        self.webView.navigationDelegate = self
    }

    func run() {
        let accessURL = inputURL.deletingLastPathComponent()
        webView.loadFileURL(inputURL, allowingReadAccessTo: accessURL)
        RunLoop.main.run()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            let configuration = WKPDFConfiguration()
            configuration.rect = self.webView.bounds

            self.webView.createPDF(configuration: configuration) { result in
                switch result {
                case .success(let data):
                    do {
                        try data.write(to: self.outputURL)
                        FileHandle.standardOutput.write(Data("PDF generated at \(self.outputURL.path)\n".utf8))
                        CFRunLoopStop(CFRunLoopGetMain())
                    } catch {
                        FileHandle.standardError.write(Data("Failed to write PDF: \(error)\n".utf8))
                        exit(1)
                    }
                case .failure(let error):
                    FileHandle.standardError.write(Data("Failed to render PDF: \(error)\n".utf8))
                    exit(1)
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        FileHandle.standardError.write(Data("Navigation failed: \(error)\n".utf8))
        exit(1)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        FileHandle.standardError.write(Data("Provisional navigation failed: \(error)\n".utf8))
        exit(1)
    }
}

let arguments = CommandLine.arguments

guard arguments.count == 3 else {
    FileHandle.standardError.write(Data("Usage: swift generate_final_report.swift <input.html> <output.pdf>\n".utf8))
    exit(1)
}

let inputURL = URL(fileURLWithPath: arguments[1])
let outputURL = URL(fileURLWithPath: arguments[2])

guard FileManager.default.fileExists(atPath: inputURL.path) else {
    FileHandle.standardError.write(Data("Input file not found: \(inputURL.path)\n".utf8))
    exit(1)
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)

let renderer = PDFRenderer(inputURL: inputURL, outputURL: outputURL)
renderer.run()
