#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

// Only geometry of the identified IntelliJ process; no window pixels or other apps.
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        pid_t pid = (pid_t)strtol(argv[1], NULL, 10);
        if (pid <= 0) return 2;
        NSArray *all = CFBridgingRelease(CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID));
        NSMutableArray *windows = [NSMutableArray array];
        for (NSDictionary *window in all) {
            if ([window[(__bridge NSString *)kCGWindowOwnerPID] intValue] != pid ||
                [window[(__bridge NSString *)kCGWindowLayer] intValue] != 0) continue;
            [windows addObject:@{
                @"bounds": window[(__bridge NSString *)kCGWindowBounds],
                @"title": window[(__bridge NSString *)kCGWindowName] ?: @"",
            }];
        }
        CGRect screen = CGDisplayBounds(CGMainDisplayID());
        NSDictionary *result = @{@"windows": windows,
            @"screen": @[@(screen.size.width), @(screen.size.height)]};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
    }
}
