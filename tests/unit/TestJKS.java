/*
Simple Unit Test for Java JKS trustsotres.
This program tries to verify a TLS/HTTPS server using a provided truststore and exits with 0 if succeeded, or 1 otherwise.
Inspired by: https://gist.github.com/dportabella/7024146
*/

import java.io.*;
import java.net.*;

class TestJKS {
  final static String usage = "java -Djavax.net.ssl.trustStore=your_trust_store.jks TestJKS <url> [<user> <password>]";
	public static void main(String[] args) {
		if (args.length != 1 && args.length != 3) {
			System.err.println(usage);
			System.exit(1);
		}

		final String url = args[0];

		if (args.length > 1) {
			final String user = args[1];
			final String password = args[2];

			Authenticator.setDefault(new Authenticator() {
				protected PasswordAuthentication getPasswordAuthentication() {
					return new PasswordAuthentication(user, password.toCharArray());
				}
			});
		}

		InputStream in = null;
		try {
			in = new java.net.URL(url).openStream();
			byte[] buffer = new byte[1024];
			int read;
			while ((read = in.read(buffer)) > 0) {
				System.out.write(buffer, 0, read);
			}
		} catch (IOException e) {
			e.printStackTrace(System.err);
			System.exit(1);
		} finally {
			if (in != null) {
				try { in.close(); } catch (Exception e) {}
			}
		}

		System.exit(0);
	}
}
