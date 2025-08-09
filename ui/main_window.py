import sys
from PyQt5.QtWidgets import (
    QMainWindow, QApplication, QFileDialog, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QListWidget,
    QHBoxLayout, QLabel, QToolBar, QAction, QMenu, QMessageBox,
    QDockWidget, QHeaderView
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QKeySequence
from db.database import get_session_and_models
from db import models
from sqlalchemy import text, inspect
import clipboard


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_path = ""
        self.setWindowTitle("SQLite DB Editor")
        self.setGeometry(100, 100, 1200, 800)

        self.edited_cells = {}
        self.undo_stack = []
        self.redo_stack = []
        self.current_table_name = None
        self.error_rows = set()
        self.edited_rows = set()
        self.new_rows = {}
        self.new_row_counter = 0

        self.show_required_fields = False
        self.highlight_nulls = False
        self.highlight_empty_strings = False

        self.error_details = {}

        self.setup_ui()
        self.setup_toolbar()
        self.setup_menu()
        self.setup_status_bar()
        self.open_db_dialog()

    def setup_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        self.tables_dock = QDockWidget("Tables", self)
        self.tables_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.table_list_widget = QListWidget()
        self.table_list_widget.currentItemChanged.connect(self.on_table_selected)
        self.tables_dock.setWidget(self.table_list_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.tables_dock)

        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("Data:"))
        self.table_view = QTableWidget()
        self.table_view.itemChanged.connect(self.handle_item_changed)
        self.table_view.cellClicked.connect(self.display_error_info)
        self.table_view.setSelectionBehavior(QTableWidget.SelectItems)
        self.table_view.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table_view.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
        right_panel.addWidget(self.table_view)

        main_layout.addLayout(right_panel, 4)

    def setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        self.save_action = QAction("Save Edits", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setStatusTip("Save all pending edits to the database")
        self.save_action.triggered.connect(self.save_edits)
        toolbar.addAction(self.save_action)

        self.make_null_action = QAction("Make Null", self)
        self.make_null_action.setShortcut("Ctrl+K")
        self.make_null_action.setStatusTip("Set the value of selected cells to NULL")
        self.make_null_action.triggered.connect(self.make_null_selected_cells)
        toolbar.addAction(self.make_null_action)

        self.new_row_action = QAction("Create New Row", self)
        self.new_row_action.setShortcut("Ctrl+N")
        self.new_row_action.setStatusTip("Add a new empty row to the current table")
        self.new_row_action.triggered.connect(self.create_new_row)
        toolbar.addAction(self.new_row_action)

        self.duplicate_row_action = QAction("Duplicate Row", self)
        self.duplicate_row_action.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicate_row_action.setStatusTip("Duplicate the selected row")
        self.duplicate_row_action.triggered.connect(self.duplicate_selected_row)
        toolbar.addAction(self.duplicate_row_action)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut("Ctrl+R")
        self.refresh_action.setStatusTip("Refresh the current table view")
        self.refresh_action.triggered.connect(self.refresh_data)
        toolbar.addAction(self.refresh_action)

        self.delete_action = QAction("Delete Row", self)
        self.delete_action.setShortcut("Del")
        self.delete_action.setStatusTip("Delete the selected row(s) from the database")
        self.delete_action.triggered.connect(self.delete_selected_rows)
        toolbar.addAction(self.delete_action)

        toolbar.addSeparator()

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setStatusTip("Undo the last change")
        self.undo_action.triggered.connect(self.undo_edit)
        toolbar.addAction(self.undo_action)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut("Ctrl+Y")
        self.redo_action.setStatusTip("Redo the last undone change")
        self.redo_action.triggered.connect(self.redo_edit)
        toolbar.addAction(self.redo_action)

        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        view_menu = menubar.addMenu("&View")
        help_menu = menubar.addMenu("&Help")

        self.open_db_action = QAction("&Open New Database...", self)
        self.open_db_action.setShortcut("Ctrl+O")
        self.open_db_action.setStatusTip("Open a different SQLite database file")
        self.open_db_action.triggered.connect(self.open_db_dialog)
        file_menu.addAction(self.open_db_action)
        file_menu.addSeparator()

        exit_action = QAction("&Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Exit the application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.toggle_tables_pane_action = self.tables_dock.toggleViewAction()
        self.toggle_tables_pane_action.setText("Show/Hide Tables Pane")
        view_menu.addAction(self.toggle_tables_pane_action)
        view_menu.addSeparator()

        self.toggle_errors_action = QAction("Show Errors Only", self, checkable=True)
        self.toggle_errors_action.setStatusTip("Toggle to show only rows with data type errors")
        self.toggle_errors_action.triggered.connect(self.toggle_error_filter)
        view_menu.addAction(self.toggle_errors_action)

        self.toggle_required_fields_action = QAction("Show Required Fields", self, checkable=True)
        self.toggle_required_fields_action.setStatusTip("Add an asterisk to required fields")
        self.toggle_required_fields_action.triggered.connect(self.toggle_required_fields)
        view_menu.addAction(self.toggle_required_fields_action)

        self.toggle_nulls_action = QAction("Highlight Null Fields", self, checkable=True)
        self.toggle_nulls_action.setStatusTip("Highlight cells that contain a NULL value")
        self.toggle_nulls_action.triggered.connect(self.toggle_highlight_nulls)
        view_menu.addAction(self.toggle_nulls_action)

        self.toggle_empty_strings_action = QAction("Highlight Empty String Fields", self, checkable=True)
        self.toggle_empty_strings_action.setStatusTip("Highlight cells that contain an empty string")
        self.toggle_empty_strings_action.triggered.connect(self.toggle_highlight_empty_strings)
        view_menu.addAction(self.toggle_empty_strings_action)

        keybinds_action = QAction("&Keybinds", self)
        keybinds_action.triggered.connect(self.show_keybinds_help)
        help_menu.addAction(keybinds_action)

    def setup_status_bar(self):
        self.statusBar = self.statusBar()
        self.error_label = QLabel("Click on a red cell to see the error details.")
        self.value_label = QLabel("Value: None")
        self.statusBar.addWidget(self.error_label)
        self.statusBar.addPermanentWidget(self.value_label)
        self.statusBar.setSizeGripEnabled(False)

    def make_null_selected_cells(self):
        selected_items = self.table_view.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select one or more cells to make NULL.")
            return

        self.table_view.itemChanged.disconnect()

        for item in selected_items:
            row, col = item.row(), item.column()

            if (row, col) not in self.edited_cells:
                original_value = item.text()
                self.edited_cells[(row, col)] = original_value

                self.undo_stack.append({
                    "row": row, "col": col,
                    "original": original_value,
                    "new": ""
                })
                self.undo_action.setEnabled(True)
                self.redo_stack.clear()
                self.redo_action.setEnabled(False)

                if len(self.undo_stack) > 10:
                    self.undo_stack.pop(0)

            item.setText("")
            item.setBackground(QColor(255, 255, 150))
            self.edited_rows.add(row)

        self.table_view.itemChanged.connect(self.handle_item_changed)
        self.statusBar.showMessage(f"Set {len(selected_items)} cells to NULL. Don't forget to save.", 2000)

    def open_db_dialog(self):
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Open Database File",
            "",
            "SQLite Database Files (*.db *.sqlite)"
        )
        if fname:
            self.db_path = fname
            print(f"Selected database: {self.db_path}")

            session, models_dict = get_session_and_models(self.db_path)

            if session and models_dict:
                models.DB_SESSION = session
                models.DB_MODELS = models_dict
                print("Database schema loaded successfully.")
                self.populate_table_list()
                self.table_view.clear()
                self.edited_cells.clear()
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.undo_action.setEnabled(False)
                self.redo_action.setEnabled(False)
                self.error_details.clear()
            else:
                QMessageBox.critical(self, "Error", "Failed to load database schema. Please check the file.")
                self.table_view.clear()
                self.table_list_widget.clear()

    def closeEvent(self, event):
        if self.edited_cells or self.new_rows:
            reply = self.prompt_for_unsaved_changes()
            if reply == QMessageBox.Save:
                self.save_edits()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def prompt_for_unsaved_changes(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Unsaved Changes")
        msg_box.setText("You have unsaved changes. Do you want to save them before proceeding?")
        msg_box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Save)
        return msg_box.exec_()

    def refresh_data(self):
        if self.edited_cells or self.new_rows:
            reply = self.prompt_for_unsaved_changes()
            if reply == QMessageBox.Save:
                self.save_edits()
            elif reply == QMessageBox.Cancel:
                return

        current_scroll_position = self.table_view.verticalScrollBar().value()

        if self.current_table_name:
            self.populate_table_view(self.current_table_name)

        self.table_view.verticalScrollBar().setValue(current_scroll_position)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C:
            self.copy_selected_cells()
        elif event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_from_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selected_cells(self):
        selected_items = self.table_view.selectedItems()
        if not selected_items:
            return

        sorted_items = sorted(selected_items, key=lambda x: (x.row(), x.column()))

        min_row = sorted_items[0].row()
        max_row = sorted_items[-1].row()
        min_col = min(item.column() for item in sorted_items)
        max_col = max(item.column() for item in sorted_items)

        data = [['' for _ in range(max_col - min_col + 1)] for _ in range(max_row - min_row + 1)]

        for item in sorted_items:
            row_index = item.row() - min_row
            col_index = item.column() - min_col
            data[row_index][col_index] = item.text()

        clipboard_text = "\n".join(["\t".join(row) for row in data])
        QApplication.clipboard().setText(clipboard_text)
        self.statusBar.showMessage(f"Copied {len(selected_items)} cells to clipboard.", 2000)

    def paste_from_clipboard(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text:
            return

        selected_items = self.table_view.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Paste Error", "Please select a starting cell to paste.")
            return

        start_item = sorted(selected_items, key=lambda x: (x.row(), x.column()))[0]
        start_row = start_item.row()
        start_col = start_item.column()

        rows_to_paste = clipboard_text.split('\n')

        self.table_view.itemChanged.disconnect()

        headers = [column.key for column in models.DB_MODELS[self.current_table_name].__table__.columns]

        try:
            for i, row_data in enumerate(rows_to_paste):
                values = row_data.split('\t')
                for j, value in enumerate(values):
                    target_row = start_row + i
                    target_col = start_col + j

                    if target_row >= self.table_view.rowCount() or target_col >= self.table_view.columnCount():
                        continue

                    item = self.table_view.item(target_row, target_col)
                    if not item:
                        item = QTableWidgetItem()
                        self.table_view.setItem(target_row, target_col, item)

                    original_value = item.text()

                    column_name = headers[target_col]
                    column_obj = models.DB_MODELS[self.current_table_name].__table__.columns.get(column_name)

                    converted_value = None
                    try:
                        if "INTEGER" in str(column_obj.type).upper():
                            converted_value = int(value)
                        elif "REAL" in str(column_obj.type).upper() or "FLOAT" in str(column_obj.type).upper():
                            converted_value = float(value)
                        elif "BOOLEAN" in str(column_obj.type).upper():
                            converted_value = value.lower() in ('true', 't', '1')
                        else:
                            converted_value = value
                    except (ValueError, TypeError):
                        QMessageBox.warning(self, "Paste Error",
                                            f"Cannot paste '{value}' into column '{column_name}' due to a type mismatch.")
                        self.table_view.itemChanged.connect(self.handle_item_changed)
                        return

                    if (target_row, target_col) not in self.edited_cells:
                        self.edited_cells[(target_row, target_col)] = original_value
                        self.undo_stack.append({"row": target_row, "col": target_col, "original": original_value,
                                                "new": str(converted_value)})
                        self.undo_action.setEnabled(True)
                        if len(self.undo_stack) > 10:
                            self.undo_stack.pop(0)

                    item.setText(str(converted_value))
                    item.setBackground(QColor(255, 255, 150))

                    self.edited_rows.add(target_row)
                    header_item = self.table_view.verticalHeaderItem(target_row)
                    if not header_item:
                        header_item = QTableWidgetItem()
                        self.table_view.setVerticalHeaderItem(target_row, header_item)

                    if not header_item.text().endswith(' *'):
                        header_item.setText(str(target_row + 1) + ' *')

        finally:
            self.table_view.itemChanged.connect(self.handle_item_changed)

    def populate_table_list(self):
        self.table_list_widget.clear()
        self.current_table_name = None
        for table_name in models.DB_MODELS.keys():
            self.table_list_widget.addItem(table_name)

    def on_table_selected(self, current_item, previous_item):
        if current_item:
            self.current_table_name = current_item.text()
            self.populate_table_view(self.current_table_name)

    def populate_table_view(self, model_name):
        self.table_view.itemChanged.disconnect()
        self.table_view.clear()
        self.table_view.setRowCount(0)
        self.table_view.setColumnCount(0)
        self.edited_cells.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.error_rows.clear()
        self.edited_rows.clear()
        self.new_rows.clear()
        self.error_details.clear()
        self.toggle_errors_action.setChecked(False)
        self.error_label.setText("Click on a red cell to see the error details.")
        self.value_label.setText("Value: None")

        if model_name in models.DB_MODELS:
            TableClass = models.DB_MODELS[model_name]
            session = models.DB_SESSION
            engine = session.bind

            headers = [column.key for column in TableClass.__table__.columns]
            self.table_view.setColumnCount(len(headers))
            self.table_view.setHorizontalHeaderLabels(headers)

            self.table_view.verticalHeader().setSectionsClickable(True)
            self.table_view.verticalHeader().sectionClicked.connect(self.display_row_error_info)

            self.update_required_fields_headers()

            try:
                with engine.connect() as connection:
                    statement = text(f"SELECT * FROM {model_name}")
                    result = connection.execute(statement)
                    rows = result.fetchall()
            except Exception as e:
                QMessageBox.critical(self, "Query Error", f"Failed to query table '{model_name}': {e}")
                self.table_view.itemChanged.connect(self.handle_item_changed)
                return

            inspector = inspect(engine)
            column_info = {c['name']: {'type': c['type'], 'nullable': c['nullable']} for c in
                           inspector.get_columns(model_name)}

            self.table_view.setRowCount(len(rows))

            for row_idx, row_tuple in enumerate(rows):
                self.table_view.setVerticalHeaderItem(row_idx, QTableWidgetItem(str(row_idx + 1)))
                is_row_invalid = False
                for col_idx, value in enumerate(row_tuple):
                    header = headers[col_idx]
                    col_info = column_info.get(header)
                    column_type = str(col_info['type']).upper() if col_info else 'TEXT'
                    column_nullable = col_info['nullable'] if col_info else True

                    is_null = (value is None)
                    is_empty_string = (isinstance(value, str) and value == "")
                    value_str = str(value) if value is not None else ""

                    item = QTableWidgetItem(value_str)

                    is_invalid = False

                    # Check for data type mismatch first
                    if not is_null and not is_empty_string:
                        try:
                            if "INTEGER" in column_type:
                                int(value)
                            elif "REAL" in column_type or "FLOAT" in column_type:
                                float(value)
                        except (ValueError, TypeError):
                            is_invalid = True
                            tooltip_text = f"Data type mismatch! Expected {column_type}, but found a non-numeric value: '{value_str}'."
                            self.error_details[(row_idx, col_idx)] = {
                                "message": tooltip_text,
                                "value": value,
                                "is_null": is_null,
                                "is_empty": is_empty_string
                            }

                    # Check for non-nullable fields with empty data
                    if not is_invalid and not column_nullable and (is_null or is_empty_string):
                        is_invalid = True
                        tooltip_text = f"Non-nullable field is empty! Column '{header}' requires a value."
                        self.error_details[(row_idx, col_idx)] = {
                            "message": tooltip_text,
                            "value": value,
                            "is_null": is_null,
                            "is_empty": is_empty_string
                        }

                    if is_invalid:
                        item.setBackground(QColor(255, 100, 100))
                        item.setToolTip(tooltip_text)
                        is_row_invalid = True

                    if not is_invalid:
                        if self.highlight_nulls and is_null:
                            item.setBackground(QColor(255, 230, 230))
                        elif self.highlight_empty_strings and is_empty_string:
                            item.setBackground(QColor(255, 230, 230))

                    self.table_view.setItem(row_idx, col_idx, item)

                if is_row_invalid:
                    self.error_rows.add(row_idx)
                    header_item = self.table_view.verticalHeaderItem(row_idx)
                    header_item.setBackground(QColor(255, 100, 100))

        self.table_view.itemChanged.connect(self.handle_item_changed)

    def update_required_fields_headers(self):
        if not self.current_table_name:
            return

        headers = [column.key for column in models.DB_MODELS[self.current_table_name].__table__.columns]
        header_labels = []
        if self.show_required_fields:
            for column in models.DB_MODELS[self.current_table_name].__table__.columns:
                label = column.key
                if not column.nullable and not column.primary_key:
                    label += " *"
                header_labels.append(label)
        else:
            header_labels = headers
        self.table_view.setHorizontalHeaderLabels(header_labels)

    def toggle_required_fields(self, checked):
        self.show_required_fields = checked
        self.update_required_fields_headers()

    def toggle_highlight_nulls(self, checked):
        self.highlight_nulls = checked
        self.populate_table_view(self.current_table_name)

    def toggle_highlight_empty_strings(self, checked):
        self.highlight_empty_strings = checked
        self.populate_table_view(self.current_table_name)

    def create_new_row(self):
        if not self.current_table_name:
            QMessageBox.warning(self, "Warning", "Please select a table from the left panel before creating a new row.")
            return

        row_count = self.table_view.rowCount()
        self.table_view.insertRow(row_count)

        self.new_row_counter += 1
        temp_id = f"NEW_{self.new_row_counter}"
        self.new_rows[row_count] = temp_id

        header_item = QTableWidgetItem(f"{row_count + 1} *")
        header_item.setBackground(QColor(255, 255, 150))
        self.table_view.setVerticalHeaderItem(row_count, header_item)

        self.edited_rows.add(row_count)
        self.table_view.scrollToBottom()

    def duplicate_selected_row(self):
        selected_rows = sorted(list(set(item.row() for item in self.table_view.selectedItems())))
        if not selected_rows or len(selected_rows) > 1:
            QMessageBox.warning(self, "Warning", "Please select exactly one row to duplicate.")
            return

        row_to_duplicate = selected_rows[0]
        row_count = self.table_view.rowCount()
        self.table_view.insertRow(row_count)

        self.new_row_counter += 1
        temp_id = f"NEW_{self.new_row_counter}"
        self.new_rows[row_count] = temp_id

        header_item = QTableWidgetItem(f"{row_count + 1} *")
        header_item.setBackground(QColor(255, 255, 150))
        self.table_view.setVerticalHeaderItem(row_count, header_item)

        primary_key_column_idx = self.get_primary_key_column_index()

        for col_idx in range(self.table_view.columnCount()):
            original_item = self.table_view.item(row_to_duplicate, col_idx)
            if original_item:
                new_item = QTableWidgetItem(original_item.text())

                if col_idx == primary_key_column_idx:
                    new_item.setText("")

                new_item.setBackground(QColor(255, 255, 150))
                self.table_view.setItem(row_count, col_idx, new_item)

        self.edited_rows.add(row_count)
        self.table_view.scrollToBottom()

    def toggle_error_filter(self):
        show_errors_only = self.toggle_errors_action.isChecked()
        for row_idx in range(self.table_view.rowCount()):
            is_error_row = row_idx in self.error_rows
            if show_errors_only:
                self.table_view.setRowHidden(row_idx, not is_error_row)
            else:
                self.table_view.setRowHidden(row_idx, False)

    def display_error_info(self, row, col):
        item = self.table_view.item(row, col)

        value = "NULL" if item is None or item.text() == "" else item.text()
        self.value_label.setText(f"Value: '{value}'")

        if (row, col) in self.error_details:
            self.error_label.setText(self.error_details[(row, col)]["message"])
        else:
            self.error_label.setText("No data type error in this cell.")

    def display_row_error_info(self, row):
        header_item = self.table_view.verticalHeaderItem(row)
        if header_item and header_item.background().color() == QColor(255, 100, 100):
            for col in range(self.table_view.columnCount()):
                if (row, col) in self.error_details:
                    self.display_error_info(row, col)
                    return
        else:
            self.error_label.setText("Click on a red cell to see the error details.")
            self.value_label.setText("Value: None")

    def handle_item_changed(self, item):
        row = item.row()
        col = item.column()

        self.table_view.itemChanged.disconnect()

        if (row, col) not in self.edited_cells:
            original_value = self.get_original_value(row, col)
            self.edited_cells[(row, col)] = original_value

            self.undo_stack.append({
                "row": row, "col": col,
                "original": original_value,
                "new": item.text()
            })
            self.undo_action.setEnabled(True)
            self.redo_stack.clear()
            self.redo_action.setEnabled(False)

            if len(self.undo_stack) > 10:
                self.undo_stack.pop(0)

        item.setBackground(QColor(255, 255, 150))

        header_item = self.table_view.verticalHeaderItem(row)
        if not header_item:
            header_item = QTableWidgetItem(str(row + 1))
            self.table_view.setVerticalHeaderItem(row, header_item)

        if not header_item.text().endswith(' *'):
            header_item.setText(header_item.text() + ' *')
            header_item.setBackground(QColor(255, 255, 150))
            self.edited_rows.add(row)

        self.table_view.itemChanged.connect(self.handle_item_changed)

    def get_original_value(self, row, col):
        if not self.current_table_name:
            return ""

        TableClass = models.DB_MODELS[self.current_table_name]
        session = models.DB_SESSION
        engine = session.bind

        headers = [column.key for column in TableClass.__table__.columns]
        column_name = headers[col]

        primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key
        primary_key_item = self.table_view.item(row, headers.index(primary_key_column))

        if primary_key_item:
            primary_key_value = primary_key_item.text().strip(' *')

            try:
                with engine.connect() as connection:
                    statement = text(
                        f"SELECT {column_name} FROM {self.current_table_name} WHERE {primary_key_column} = :pk_value")
                    result = connection.execute(statement, {"pk_value": primary_key_value}).scalar()
                    return str(result) if result is not None else ""
            except Exception as e:
                print(f"Error fetching original value: {e}")
                return ""
        return ""

    def get_primary_key_column_index(self):
        if self.current_table_name:
            TableClass = models.DB_MODELS[self.current_table_name]
            try:
                primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key
                headers = [column.key for column in TableClass.__table__.columns]
                return headers.index(primary_key_column)
            except (KeyError, IndexError):
                return None
        return None

    def save_edits(self):
        if not self.edited_cells and not self.new_rows:
            QMessageBox.information(self, "No Edits", "There are no unsaved changes to commit.")
            return

        if not self.current_table_name:
            QMessageBox.warning(self, "Warning", "Please select a table first.")
            return

        TableClass = models.DB_MODELS[self.current_table_name]
        session = models.DB_SESSION

        current_scroll_position = self.table_view.verticalScrollBar().value()

        # New validation logic: Collect all errors and display them at once
        validation_errors = []
        headers = [column.key for column in TableClass.__table__.columns]
        inspector = inspect(session.bind)
        column_info = {c['name']: {'type': c['type'], 'nullable': c['nullable']} for c in
                       inspector.get_columns(self.current_table_name)}

        all_changed_rows = self.edited_rows.union(self.new_rows.keys())

        for row_index in sorted(list(all_changed_rows)):
            for col_index, column_name in enumerate(headers):
                item = self.table_view.item(row_index, col_index)
                if not item:
                    continue

                value = item.text()
                col_info = column_info.get(column_name)
                column_type = str(col_info['type']).upper()
                column_nullable = col_info['nullable']

                is_null_or_empty = (value == "" or value == "None")

                # Check for non-nullable fields with empty data
                if not column_nullable and is_null_or_empty:
                    validation_errors.append(
                        f"Row {row_index + 1}, Column '{column_name}': Non-nullable field is empty."
                    )

                # Check for data type mismatch
                if not is_null_or_empty:
                    try:
                        if "INTEGER" in column_type:
                            int(value)
                        elif "REAL" in column_type or "FLOAT" in column_type:
                            float(value)
                    except (ValueError, TypeError):
                        validation_errors.append(
                            f"Row {row_index + 1}, Column '{column_name}': Data type mismatch. Expected {column_type}, but got '{value}'."
                        )

        if validation_errors:
            error_message = "The following errors must be fixed before saving:\n\n"
            error_message += "\n".join(validation_errors)
            QMessageBox.warning(self, "Validation Error", error_message)
            return

        # If no validation errors, proceed with the save logic
        try:
            for row_index, temp_id in self.new_rows.items():
                new_object_data = {}
                for col_index, column_name in enumerate(headers):
                    if column_name == TableClass.__table__.primary_key.columns.values()[0].key:
                        continue

                    item = self.table_view.item(row_index, col_index)
                    value = item.text() if item else None

                    column_obj = TableClass.__table__.columns.get(column_name)

                    if value in ["", "None"]:
                        new_object_data[column_name] = None
                        continue

                    try:
                        if "INTEGER" in str(column_obj.type).upper():
                            converted_value = int(value)
                        elif "REAL" in str(column_obj.type).upper() or "FLOAT" in str(column_obj.type).upper():
                            converted_value = float(value)
                        elif "BOOLEAN" in str(column_obj.type).upper():
                            converted_value = value.lower() in ('true', 't', '1')
                        else:
                            converted_value = value
                        new_object_data[column_name] = converted_value
                    except ValueError:
                        pass

                new_object = TableClass(**new_object_data)
                session.add(new_object)

            for (row, col), original_value in self.edited_cells.items():
                is_new_row_edit = row in self.new_rows
                if is_new_row_edit:
                    continue

                column_name = headers[col]
                column_obj = TableClass.__table__.columns.get(column_name)
                primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key

                primary_key_item = self.table_view.item(row, headers.index(primary_key_column))
                if not primary_key_item: continue
                primary_key_value = primary_key_item.text().strip(' *')

                obj_to_update = session.query(TableClass).filter_by(**{primary_key_column: primary_key_value}).one()

                new_value = self.table_view.item(row, col).text()

                if new_value in ["", "None"]:
                    setattr(obj_to_update, column_name, None)
                    continue

                try:
                    if "INTEGER" in str(column_obj.type).upper():
                        converted_value = int(new_value)
                    elif "REAL" in str(column_obj.type).upper() or "FLOAT" in str(column_obj.type).upper():
                        converted_value = float(new_value)
                    elif "BOOLEAN" in str(column_obj.type).upper():
                        converted_value = new_value.lower() in ('true', 't', '1')
                    else:
                        converted_value = new_value
                except ValueError:
                    pass

                setattr(obj_to_update, column_name, converted_value)

            session.commit()
            QMessageBox.information(self, "Success", "Changes saved to database.")

        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "Database Error", f"Failed to save changes: {e}")
            print(f"Error during save: {e}")

        finally:
            self.edited_cells.clear()
            self.new_rows.clear()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.undo_action.setEnabled(False)
            self.redo_action.setEnabled(False)
            self.edited_rows.clear()
            self.populate_table_view(self.current_table_name)
            self.table_view.verticalScrollBar().setValue(current_scroll_position)

    def delete_selected_rows(self):
        selected_rows = sorted(list(set(item.row() for item in self.table_view.selectedItems())), reverse=True)

        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select one or more rows to delete.")
            return

        reply = QMessageBox.question(self, "Confirm Deletion",
                                     f"Are you sure you want to delete {len(selected_rows)} row(s)? This cannot be undone.",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            session = models.DB_SESSION
            TableClass = models.DB_MODELS[self.current_table_name]
            primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key

            rows_to_delete_from_db = []
            new_rows_to_remove = []

            headers = [column.key for column in TableClass.__table__.columns]
            pk_col_idx = headers.index(primary_key_column)

            for row_idx in selected_rows:
                if row_idx in self.new_rows:
                    new_rows_to_remove.append(row_idx)
                else:
                    item = self.table_view.item(row_idx, pk_col_idx)
                    if item:
                        primary_key_value = item.text().strip(' *')
                        rows_to_delete_from_db.append(primary_key_value)

            try:
                for pk_value in rows_to_delete_from_db:
                    obj_to_delete = session.query(TableClass).filter_by(**{primary_key_column: pk_value}).one()
                    session.delete(obj_to_delete)

                session.commit()
                QMessageBox.information(self, "Success",
                                        f"Deleted {len(rows_to_delete_from_db)} row(s) from the database.")
            except Exception as e:
                session.rollback()
                QMessageBox.critical(self, "Database Error", f"Failed to delete rows: {e}")
                print(f"Error during delete: {e}")
                return

            for row_idx in sorted(selected_rows):
                self.table_view.removeRow(row_idx)

            self.new_rows = {k: v for k, v in self.new_rows.items() if k not in new_rows_to_remove}
            self.edited_cells = {k: v for k, v in self.edited_cells.items() if k[0] not in selected_rows}

    def undo_edit(self):
        if not self.undo_stack:
            return

        last_edit = self.undo_stack.pop()
        self.redo_stack.append(last_edit)

        row = last_edit["row"]
        col = last_edit["col"]
        original_value = last_edit["original"]

        self.table_view.itemChanged.disconnect()
        item = self.table_view.item(row, col)
        if item:
            item.setText(original_value)

            is_still_edited = False
            for r, c in self.edited_cells:
                if r == row and (r, c) != (row, col):
                    is_still_edited = True
                    break

            if not is_still_edited:
                self.edited_rows.discard(row)
                header_item = self.table_view.verticalHeaderItem(row)
                if header_item and header_item.text().endswith(' *'):
                    header_item.setText(header_item.text().strip(' *'))
                    header_item.setBackground(QColor(255, 255, 255))

            if (row, col) in self.edited_cells and self.edited_cells[(row, col)] == original_value:
                self.edited_cells.pop((row, col))
                item.setBackground(QColor(255, 255, 255))

        self.table_view.itemChanged.connect(self.handle_item_changed)

        self.undo_action.setEnabled(len(self.undo_stack) > 0)
        self.redo_action.setEnabled(True)

    def redo_edit(self):
        if not self.redo_stack:
            return

        last_undone_edit = self.redo_stack.pop()
        self.undo_stack.append(last_undone_edit)

        row = last_undone_edit["row"]
        col = last_undone_edit["col"]
        new_value = last_undone_edit["new"]

        self.table_view.itemChanged.disconnect()
        item = self.table_view.item(row, col)
        if item:
            item.setText(new_value)
            item.setBackground(QColor(255, 255, 150))
            self.edited_rows.add(row)
            header_item = self.table_view.verticalHeaderItem(row)
            if header_item and not header_item.text().endswith(' *'):
                header_item.setText(header_item.text() + ' *')
                header_item.setBackground(QColor(255, 255, 150))

        self.table_view.itemChanged.connect(self.handle_item_changed)

        self.undo_action.setEnabled(True)
        self.redo_action.setEnabled(len(self.redo_stack) > 0)

    def show_keybinds_help(self):
        keybinds = """
        <h3>Keybinds</h3>
        <ul>
            <li><b>Ctrl+S</b>: Save all edits</li>
            <li><b>Ctrl+O</b>: Open a new database</li>
            <li><b>Ctrl+N</b>: Create a new row</li>
            <li><b>Ctrl+D</b>: Duplicate the selected row</li>
            <li><b>Ctrl+R</b>: Refresh the current table view</li>
            <li><b>Ctrl+Z</b>: Undo the last change</li>
            <li><b>Ctrl+Y</b>: Redo the last undone change</li>
            <li><b>Del</b>: Delete the selected row(s)</li>
            <li><b>Ctrl+C</b>: Copy selected cells</li>
            <li><b>Ctrl+V</b>: Paste from clipboard</li>
            <li><b>Ctrl+K</b>: Make selected cells NULL</li>
        </ul>
        """
        QMessageBox.information(self, "Keybinds", keybinds)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())