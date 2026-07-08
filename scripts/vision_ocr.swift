// Batch OCR over image files using Apple's on-device Vision framework
// (VNRecognizeTextRequest). Prints a JSON array to stdout, one object per
// input image, in the order the paths were given.
//
// Usage:
//   vision_ocr <image1> [image2 ...] [--languages en-US,fr-FR]
//
// Build:
//   swiftc -O vision_ocr.swift -o bin/vision_ocr

import CoreGraphics
import Foundation
import ImageIO
import Vision

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    // Vision bounding boxes are normalized 0-1 with origin at bottom-left.
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat
}

struct OCRResult: Codable {
    let file: String
    let path: String
    let width: Int
    let height: Int
    let text: String
    let averageConfidence: Float
    let lineCount: Int
    let lines: [OCRLine]
    let error: String?
}

func loadCGImage(url: URL) -> CGImage? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    let options: [CFString: Any] = [kCGImageSourceShouldCache: false]
    return CGImageSourceCreateImageAtIndex(source, 0, options as CFDictionary)
}

func ocrImage(at url: URL, languages: [String]) -> OCRResult {
    let path = url.path
    let name = url.lastPathComponent

    guard let image = loadCGImage(url: url) else {
        return OCRResult(
            file: name, path: path, width: 0, height: 0, text: "",
            averageConfidence: 0, lineCount: 0, lines: [],
            error: "could not decode image"
        )
    }

    var lines: [OCRLine] = []
    var errorMessage: String? = nil

    let request = VNRecognizeTextRequest { request, error in
        if let error = error {
            errorMessage = error.localizedDescription
            return
        }
        guard let observations = request.results as? [VNRecognizedTextObservation] else { return }
        for obs in observations {
            guard let candidate = obs.topCandidates(1).first else { continue }
            let box = obs.boundingBox
            lines.append(
                OCRLine(
                    text: candidate.string,
                    confidence: candidate.confidence,
                    x: box.origin.x,
                    y: box.origin.y,
                    width: box.size.width,
                    height: box.size.height
                ))
        }
    }
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    if !languages.isEmpty {
        request.recognitionLanguages = languages
    }

    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    do {
        try handler.perform([request])
    } catch {
        errorMessage = error.localizedDescription
    }

    // Approximate reading order: Vision's y origin is bottom-left, so sort
    // top-to-bottom (descending y), then left-to-right for ties.
    lines.sort { a, b in
        if abs(a.y - b.y) > 0.01 {
            return a.y > b.y
        }
        return a.x < b.x
    }

    let joinedText = lines.map { $0.text }.joined(separator: "\n")
    let avgConf =
        lines.isEmpty ? 0 : lines.map { $0.confidence }.reduce(0, +) / Float(lines.count)

    return OCRResult(
        file: name, path: path, width: image.width, height: image.height,
        text: joinedText, averageConfidence: avgConf, lineCount: lines.count,
        lines: lines, error: errorMessage
    )
}

// MARK: - main

let args = CommandLine.arguments
guard args.count > 1 else {
    FileHandle.standardError.write(
        "Usage: vision_ocr <image1> [image2 ...] [--languages en-US,fr-FR]\n".data(
            using: .utf8)!)
    exit(1)
}

var paths: [String] = []
var languages: [String] = ["en-US"]

var i = 1
while i < args.count {
    let arg = args[i]
    if arg == "--languages", i + 1 < args.count {
        languages = args[i + 1].split(separator: ",").map { String($0) }
        i += 2
        continue
    }
    paths.append(arg)
    i += 1
}

var results: [OCRResult] = []
for p in paths {
    results.append(ocrImage(at: URL(fileURLWithPath: p), languages: languages))
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
guard let data = try? encoder.encode(results),
    let json = String(data: data, encoding: .utf8)
else {
    FileHandle.standardError.write("Failed to encode JSON\n".data(using: .utf8)!)
    exit(1)
}
print(json)
