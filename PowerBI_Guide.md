# Power BI Desktop Guide: Environmental Sensor Dashboard

This guide walks you through building a professional Power BI dashboard using the processed environmental sensor data from this project. 

## Step 1: Import the Data

1. Open **Power BI Desktop**.
2. Close the welcome splash screen if it appears.
3. On the Home ribbon, click **Get Data** > **Text/CSV**.
4. Navigate to your project folder: `Environmental Sensor Anomaly Detection & Dashboard/data/processed/`.
5. Select **`sensor_data_processed.csv`** and click **Open**.
6. A preview window will appear. Do not click "Load" yet. Instead, click **Transform Data** to open the Power Query Editor.

## Step 2: Check and Fix Data Types

In the Power Query Editor, ensure Power BI understands the format of your data.

1. **Check the `timestamp` column**: 
   - Look at the icon next to the column name `timestamp`. It should look like a calendar/clock (meaning Date/Time). 
   - If it shows `ABC` (Text), right-click the column header > **Change Type** > **Date/Time**.
2. **Check the sensor columns** (`turbidity_FNU`, `pH`, etc.):
   - These should show `1.2` (Decimal Number). If not, change their type to Decimal Number.
3. **Check the flag columns** (e.g., `zscore_flag_any`):
   - These should be `123` (Whole Number).
4. Click **Close & Apply** in the top-left corner of the Home ribbon to load the data into your model.

*(Optional)*: If you want to show the Average Time-to-Alarm KPI, you'll need the event metrics file too:
- Click **Get Data** > **Text/CSV** again, select `per_event_metrics.csv`. Click **Load**.

## Step 3: Write DAX Measures for KPI Cards

DAX (Data Analysis Expressions) is Power BI's formula language. We need a measure to calculate the percentage of anomalous readings.

1. On the right side of the screen, find the **Data** pane (it lists your table `sensor_data_processed`).
2. Right-click the table name and select **New Measure**.
3. A formula bar will appear at the top. Paste the following exact code:

```dax
% Flagged Anomalies = 
DIVIDE (
    CALCULATE ( COUNTROWS('sensor_data_processed'), 'sensor_data_processed'[zscore_flag_any] = 1 ),
    COUNTROWS('sensor_data_processed'),
    0
)
```
*Note: This formula counts all rows where the flag is 1, and divides it by the total number of rows. The `0` at the end prevents divide-by-zero errors.*

4. After pasting, press **Enter**.
5. With the measure still selected, click the **%** icon in the **Measure tools** ribbon at the top to format it as a percentage.

*(Optional)* If you imported `per_event_metrics`, let's create a measure for Average Time to Alarm:
1. Right-click `per_event_metrics` > **New Measure**.
2. Paste:
```dax
Avg Time to Alarm (min) = AVERAGE('per_event_metrics'[tta_minutes])
```
3. Press **Enter**.

## Step 4: Build the Visuals

Now let's arrange the visuals on the report canvas.

### 1. KPI Cards
1. Go to the **Visualizations** pane and click the **Card** visual (it looks like a rectangle with '123' on it).
2. An empty card will appear on the canvas. Drag your **`% Flagged Anomalies`** measure from the Data pane into the "Fields" area of the Visualizations pane.
3. Resize the card and place it at the top left.
4. *(Optional)* Add another Card visual and drag in the **`Avg Time to Alarm (min)`** measure.

### 2. Time-Series Line Chart
1. Click the blank canvas to deselect the card.
2. Click the **Line Chart** icon in the Visualizations pane.
3. In the Data pane, find the `timestamp` column and drag it to the **X-axis** bucket. 
   *(Power BI might automatically turn this into a Date Hierarchy (Year > Quarter > Month > Day). To view the raw timestamps, click the down arrow next to `timestamp` in the X-axis bucket and select `timestamp` instead of `Date Hierarchy`).*
4. Drag your sensor columns (e.g., `turbidity_FNU`, `pH`) into the **Y-axis** bucket.
5. To highlight anomalies, you have two options:
   - **Option A (Filter Toggle / Slicer):** Add a **Slicer** visual to the page. Drag `zscore_flag_any` into it. You can now toggle between 0 (normal) and 1 (anomaly) to filter the line chart.
   - **Option B (Separate Series):** Drag `zscore_flag_any` into the **Legend** bucket of the line chart. Power BI will draw two lines—one for normal readings (0) and one for anomalies (1). Go to the **Format your visual** tab (the paintbrush icon) > **Lines** > **Colors** to make the '1' line red.

### 3. Anomaly Table
1. Click the blank canvas.
2. Click the **Table** icon in the Visualizations pane.
3. Drag the following fields into the **Columns** bucket:
   - `timestamp` (Remember to switch it from Date Hierarchy to just `timestamp`)
   - `zscore_flag_any`
   - `zscore_turbidity_FNU` (and any other z-scores you care about)
   - `turbidity_FNU` (the raw reading)
4. We only want this table to show anomalies. With the table selected, open the **Filters** pane (usually next to Visualizations). 
5. Find the `zscore_flag_any` filter card under "Filters on this visual". 
6. Change the filter type to **Basic filtering**, check the box for **1**, and you will see only the anomalous rows!

## Step 5: Formatting and Polish

- **Titles**: Click any visual, go to the **Format your visual** tab (paintbrush) > **General** > **Title** to give it a clean, descriptive name.
- **Backgrounds**: In the Format tab, under **Effects**, you can change the background color of visuals to match your preferred theme (e.g., dark mode).
- **Layout**: Arrange the KPI cards across the top, the line charts in the middle, and the anomaly table at the bottom.

You now have a fully functional, interactive Power BI dashboard based on your real USGS anomaly detection data!
