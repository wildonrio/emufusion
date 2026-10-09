package com.thorium.preview;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.Socket;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/** Fixed HTTPS destination; no redirects, cookies, account tokens, or raw logs. */
final class PrivateDiagnosticsTransport {
    enum Result { ACCEPTED, REJECTED, RETRY }

    static URI endpoint(String value) {
        if (value == null || value.length() > 300) return null;
        try {
            URI uri = new URI(value);
            if (!"https".equals(uri.getScheme()) || uri.getHost() == null ||
                    uri.getHost().isEmpty() || uri.getRawUserInfo() != null ||
                    uri.getRawQuery() != null || uri.getRawFragment() != null ||
                    !"/v1/report".equals(uri.getRawPath()) ||
                    (uri.getPort() != -1 && uri.getPort() != 443)) return null;
            return uri;
        } catch (URISyntaxException ignored) { return null; }
    }

    static Result send(URI endpoint, PrivateDiagnosticReport report) throws IOException {
        if (endpoint == null || !endpoint.equals(endpoint(endpoint.toString())) || report == null)
            throw new IOException("Private diagnostics destination unavailable");
        return connect(endpoint.getHost(), 443, report);
    }

    static Result connect(String host, int port, PrivateDiagnosticReport report)
            throws IOException {
        // Android has no Authenticator.getDefault(). URLConnection may invoke a
        // process-global authenticator on a server/proxy challenge. This single
        // fixed request uses platform TLS directly: no cookie jar, authentication
        // callbacks, proxy credentials, redirects, cache, or automatic replay.
        try (Socket raw = new Socket(Proxy.NO_PROXY)) {
            raw.connect(new InetSocketAddress(host, port), 5000);
            raw.setSoTimeout(5000);
            try (SSLSocket tls = (SSLSocket) ((SSLSocketFactory) SSLSocketFactory.getDefault())
                    .createSocket(raw, host, port, true)) {
                SSLParameters parameters = tls.getSSLParameters();
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                tls.setSSLParameters(parameters);
                tls.setSoTimeout(5000);
                tls.startHandshake();
                return exchange(tls.getInputStream(), tls.getOutputStream(), host, report);
            }
        }
    }

    static Result exchange(InputStream input, OutputStream output, String host,
            PrivateDiagnosticReport report) throws IOException {
        if (endpoint("https://" + host + "/v1/report") == null || report == null)
            throw new IOException("Invalid private report");
        byte[] body = report.body();
        byte[] headers = ("POST /v1/report HTTP/1.1\r\nHost: " + host +
                "\r\nContent-Type: application/json\r\nUser-Agent: EmuFusion-Diagnostics/1" +
                "\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: " +
                body.length + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
        output.write(headers);
        output.write(body);
        output.flush();
        // Only the bounded status line is needed; never retain arbitrary response
        // headers/text or respond to a cookie/authentication/redirect challenge.
        StringBuilder line = new StringBuilder();
        while (line.length() < 256) {
            int next = input.read();
            if (next < 0) throw new IOException("Incomplete private report response");
            line.append((char) next);
            if (next == '\n') break;
        }
        String statusLine = line.toString();
        if (!statusLine.matches("HTTP/1\\.[01] [1-5][0-9]{2} [\\x20-\\x7e]*\\r\\n"))
            throw new IOException("Invalid private report response");
        int status = Integer.parseInt(statusLine.substring(9, 12));
        if (status == 204) return Result.ACCEPTED;
        if (status == 429 || status >= 500) return Result.RETRY;
        // Never follow redirects, inspect arbitrary response text, or send credentials.
        return Result.REJECTED;
    }
}
