import AppKit
import Foundation
import PDFKit

let args = CommandLine.arguments

guard args.count >= 3 else {
    fputs("Usage: swift inspect_pdf.swift <pdf-path> <page-index> [<page-index> ...]\n", stderr)
    exit(1)
}

let pdfURL = URL(fileURLWithPath: args[1])
guard let document = PDFDocument(url: pdfURL) else {
    fputs("Unable to open PDF: \(pdfURL.path)\n", stderr)
    exit(1)
}

print("PAGE_COUNT=\(document.pageCount)")

let outDir = pdfURL.deletingLastPathComponent().appendingPathComponent("pdf_previews", isDirectory: true)
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

for rawIndex in args.dropFirst(2) {
    guard let pageIndex = Int(rawIndex), pageIndex >= 0, pageIndex < document.pageCount else {
        fputs("Skipping invalid page index: \(rawIndex)\n", stderr)
        continue
    }

    guard let page = document.page(at: pageIndex) else {
        fputs("Unable to access page index: \(pageIndex)\n", stderr)
        continue
    }

    let pageRect = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.0
    let targetSize = NSSize(width: pageRect.width * scale, height: pageRect.height * scale)
    let image = NSImage(size: targetSize)

    image.lockFocus()
    NSColor.white.set()
    NSBezierPath(rect: NSRect(origin: .zero, size: targetSize)).fill()

    guard let context = NSGraphicsContext.current?.cgContext else {
        fputs("Unable to access graphics context for page \(pageIndex)\n", stderr)
        image.unlockFocus()
        continue
    }

    context.saveGState()
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()
    image.unlockFocus()

    guard
        let tiff = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff),
        let png = bitmap.representation(using: .png, properties: [:])
    else {
        fputs("Unable to encode PNG for page \(pageIndex)\n", stderr)
        continue
    }

    let outURL = outDir.appendingPathComponent("page-\(pageIndex + 1).png")
    try png.write(to: outURL)
    print("WROTE=\(outURL.path)")
}
