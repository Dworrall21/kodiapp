import SwiftUI

@main
struct KodiXboxRemoteApp: App {
    @StateObject private var viewModel = RemoteViewModel()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                RemoteView()
            }
            .environmentObject(viewModel)
        }
    }
}
