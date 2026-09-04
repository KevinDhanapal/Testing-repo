import java.time.format.DateTimeFormatter;
import java.time.ZoneId;
import java.util.Date;

public class Sample {
    // DateTimeFormatter is immutable and thread-safe, unlike SimpleDateFormat.
    private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    public String today(Date date) {
        return FORMATTER.format(date.toInstant().atZone(ZoneId.systemDefault()));
    }
}
