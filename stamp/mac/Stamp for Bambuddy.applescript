-- Stamp for Bambuddy: drop Centauri Carbon .gcode.3mf files (or folders) on this app.
-- It runs stamp_for_bambuddy.py, bundled in the app's Resources, with macOS's
-- built-in Python, and shows what was stamped.

on run
	set picked to choose file with prompt "Choose sliced Centauri Carbon files (.gcode.3mf) to stamp for Bambuddy:" with multiple selections allowed
	stampItems(picked)
end run

on open droppedItems
	stampItems(droppedItems)
end open

on stampItems(theItems)
	set script_path to POSIX path of (path to resource "stamp_for_bambuddy.py")
	set arguments to ""
	repeat with anItem in theItems
		set arguments to arguments & " " & quoted form of POSIX path of anItem
	end repeat
	set paths_file to (POSIX path of (path to temporary items)) & "stamp-for-bambuddy-paths.txt"
	try
		-- "; true": the script exits with 1 when it skips a file, which is not an app error.
		set report to do shell script "/usr/bin/python3 " & quoted form of script_path & " --paths-file " & quoted form of paths_file & arguments & " 2>&1; true"
	on error message
		display dialog "Could not run the stamp:" & return & return & message buttons {"OK"} default button "OK" with icon stop
		return
	end try
	if report is "" then set report to "Nothing to stamp."
	set stampedFiles to {}
	try
		repeat with aLine in paragraphs of (do shell script "cat " & quoted form of paths_file)
			if aLine as text is not "" then set end of stampedFiles to (POSIX file (aLine as text)) as alias
		end repeat
	end try
	if (count of stampedFiles) > 0 then
		set advice to "Next: in Bambuddy, open File Manager and click Upload (or drag the stamped file onto the page), then print it on the Centauri. \"Show in Finder\" selects the stamped files."
	else
		set advice to "Nothing was stamped. Only sliced Centauri Carbon files can be stamped: open the project in ElegooSlicer with the Centauri Carbon printer, slice it, then use File > Export > Export plate sliced file, and drop that file here."
	end if
	set answer to display dialog report & return & return & advice buttons {"Show in Finder", "OK"} default button "OK" with title "Stamp for Bambuddy"
	if button returned of answer is "Show in Finder" then
		tell application "Finder"
			activate
			if (count of stampedFiles) > 0 then
				reveal stampedFiles
			else
				reveal item 1 of theItems
			end if
		end tell
	end if
end stampItems
