// PentaCommandApp.swift — v3.2
// Fix: ContentView chỉ được khởi tạo SAU KHI splash kết thúc
// Nguyên nhân lỗi cũ: ContentView() tạo VoiceEngine + NetworkManager ngay lập tức
// → block main thread → splash chưa kịp render đã bị đè bởi UI chính

import SwiftUI

@main
struct PentaCommandApp: App {
    var body: some Scene {
        WindowGroup {
            AppRootView()
                .preferredColorScheme(.dark)
        }
    }
}

// MARK: - AppRootView

/// View gốc điều phối splash → main app.
/// ContentView chỉ được tạo (và VoiceEngine mới được init) sau khi splash xong.
struct AppRootView: View {
    @State private var splashDone: Bool = false

    var body: some View {
        ZStack {
            if splashDone {
                // ContentView chỉ khởi tạo tại đây — sau splash
                ContentView()
                    .transition(.opacity)
            } else {
                // Splash chiếm toàn màn hình, không có gì phía sau cả
                SplashView(onFinished: {
                    withAnimation(.easeInOut(duration: 0.5)) {
                        splashDone = true
                    }
                })
                .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.5), value: splashDone)
    }
}
