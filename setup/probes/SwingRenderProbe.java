import java.awt.*;
import java.nio.file.*;
import javax.swing.*;

/** Authored Java2D display/input fixture, run with IntelliJ's own JBR. */
public final class SwingRenderProbe {
    private static final Color[] COLORS = {
        Color.RED, Color.GREEN, Color.BLUE, Color.CYAN, Color.MAGENTA, Color.YELLOW
    };
    private static long paints;

    public static void main(String[] args) {
        Path report = Path.of(args[0]);
        SwingUtilities.invokeLater(() -> {
            JFrame frame = new JFrame("Reims Java2D regression");
            frame.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
            JPanel palette = new JPanel() {
                @Override protected void paintComponent(Graphics g) {
                    super.paintComponent(g);
                    paints++;
                    for (int i = 0; i < COLORS.length; i++) {
                        g.setColor(COLORS[i]);
                        g.fillRect(12 + i * 150, 12, 128, 80);
                        g.setColor(Color.WHITE);
                        g.drawString("COLOR " + i, 12 + i * 150, 110);
                    }
                }
            };
            palette.setBackground(new Color(48, 48, 48));
            palette.setPreferredSize(new Dimension(920, 125));
            JTextArea text = new JTextArea("reims input check");
            text.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 20));
            text.setForeground(Color.BLACK);
            text.setBackground(Color.WHITE);
            frame.add(palette, BorderLayout.NORTH);
            frame.add(new JScrollPane(text), BorderLayout.CENTER);
            frame.setBounds(100, 100, 940, 640);
            frame.setVisible(true);
            frame.toFront();
            text.requestFocusInWindow();
            Timer timer = new Timer(500, event -> {
                try {
                    Point p = palette.getLocationOnScreen();
                    StringBuilder samples = new StringBuilder();
                    for (int i = 0; i < COLORS.length; i++) {
                        if (i != 0) samples.append(',');
                        Color color = COLORS[i];
                        samples.append(String.format("{\"x\":%d,\"y\":%d,\"rgb\":[%d,%d,%d]}",
                            p.x + 12 + i * 150 + 64, p.y + 12 + 40,
                            color.getRed(), color.getGreen(), color.getBlue()));
                    }
                    Dimension screen = Toolkit.getDefaultToolkit().getScreenSize();
                    String value = String.format("{\"paints\":%d,\"inputPass\":%s," +
                        "\"metal\":\"%s\",\"graphicsConfiguration\":\"%s\",\"screen\":[%d,%d],\"samples\":[%s]}",
                        paints, text.getText().equals("reimsgpucheck"),
                        System.getProperty("sun.java2d.metal", "unset"),
                        frame.getGraphicsConfiguration().getClass().getName(),
                        screen.width, screen.height, samples);
                    Path next = report.resolveSibling(report.getFileName() + ".next");
                    Files.writeString(next, value);
                    Files.move(next, report, StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
                } catch (Exception error) {
                    error.printStackTrace();
                }
            });
            timer.start();
        });
    }
}
