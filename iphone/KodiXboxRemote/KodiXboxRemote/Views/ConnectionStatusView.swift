import SwiftUI

struct ConnectionStatusView: View {
    @EnvironmentObject var viewModel: RemoteViewModel

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(viewModel.connectionStatus.color)
                .frame(width: 12, height: 12)
            VStack(alignment: .leading, spacing: 2) {
                Text(viewModel.connectionStatus.rawValue)
                    .font(.headline)
                Text(viewModel.isListening ? "Listening on \(viewModel.localIP):\(viewModel.localPortString)" : "Listener stopped")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}
