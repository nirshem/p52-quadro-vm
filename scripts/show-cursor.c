/* spice-gtk installs a cursor named "none" when Windows hides its pointer.
   Force the normal desktop cursor so the Ubuntu pointer stays visible. */
#define _GNU_SOURCE
#include <stddef.h>
#include <dlfcn.h>

typedef void (*set_cursor_fn)(void *window, void *cursor);

void gdk_window_set_cursor(void *window, void *cursor) {
    static set_cursor_fn real;
    if (!real)
        real = (set_cursor_fn)dlsym(RTLD_NEXT, "gdk_window_set_cursor");
    (void)cursor;
    real(window, NULL);
}
