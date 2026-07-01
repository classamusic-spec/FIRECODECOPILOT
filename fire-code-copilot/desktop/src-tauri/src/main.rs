// Windows: don't pop a console window alongside the GUI in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    fire_code_copilot_desktop_lib::run()
}
