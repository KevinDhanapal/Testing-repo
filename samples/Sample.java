public class Sample {
    // Bug: SimpleDateFormat is not thread-safe but is shared via a static field.
    private static SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd");

    public String today(java.util.Date date) {
        return formatter.format(date);
    }
}
