import sys
from PyQt5.QtWidgets import (
    QMainWindow, QApplication, QFileDialog, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QListWidget,
    QHBoxLayout, QLabel, QToolBar, QAction, QMenu, QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QKeySequence
from db.database import get_session_and_models
from db import models
from sqlalchemy import text, inspect


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_path = ""
        self.setWindowTitle("SQLite DB Editor")
        self.setGeometry(100, 100, 1200, 800)

        # State management for unsaved edits
        self.edited_cells = {}  # Stores (row, col) -> original_value
        self.undo_stack = []
        self.redo_stack = []
        self.current_table_name = None
        self.error_rows = set()
        self.edited_rows = set()  # NEW: To track rows with edits

        self.setup_ui()
        self.setup_toolbar()
        self.setup_menu()
        self.setup_status_bar()
        self.open_db_dialog()

    def setup_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("Tables:"))
        self.table_list_widget = QListWidget()
        self.table_list_widget.currentItemChanged.connect(self.on_table_selected)
        left_panel.addWidget(self.table_list_widget)

        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("Data:"))
        self.table_view = QTableWidget()
        self.table_view.itemChanged.connect(self.handle_item_changed)
        self.table_view.cellClicked.connect(self.display_error_info)
        self.table_view.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_view.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
        right_panel.addWidget(self.table_view)

        main_layout.addLayout(left_panel, 1)
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

        toolbar.addSeparator()
        self.show_errors_action = QAction("Show Errors Only", self, checkable=True)
        self.show_errors_action.setStatusTip("Toggle to show only rows with data type errors")
        self.show_errors_action.triggered.connect(self.toggle_error_filter)
        toolbar.addAction(self.show_errors_action)

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
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

        keybinds_action = QAction("&Keybinds", self)
        keybinds_action.triggered.connect(self.show_keybinds_help)
        help_menu.addAction(keybinds_action)

    def setup_status_bar(self):
        self.statusBar = self.statusBar()
        self.error_label = QLabel("Click on a red cell to see the error details.")
        self.statusBar.addWidget(self.error_label)
        self.statusBar.setSizeGripEnabled(False)

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
            else:
                QMessageBox.critical(self, "Error", "Failed to load database schema. Please check the file.")
                self.table_view.clear()
                self.table_list_widget.clear()

    def closeEvent(self, event):
        if self.edited_cells:
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
        if self.edited_cells:
            reply = self.prompt_for_unsaved_changes()
            if reply == QMessageBox.Save:
                self.save_edits()
            elif reply == QMessageBox.Cancel:
                return

        self.populate_table_list()

        if self.current_table_name:
            self.populate_table_view(self.current_table_name)

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

        # Build a tab-separated string of the cell contents
        data = []
        current_row = sorted_items[0].row()
        row_data = []

        for item in sorted_items:
            if item.row() != current_row:
                data.append("\t".join(row_data))
                row_data = []
                current_row = item.row()
            row_data.append(item.text())

        data.append("\t".join(row_data))

        clipboard_text = "\n".join(data)
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

        # Get the top-left-most selected cell as the starting point
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

                    item.setText(str(converted_value))
                    item.setBackground(QColor(255, 255, 150))

                    # NEW: Add asterisk to the ID column
                    self.edited_rows.add(target_row)
                    primary_key_column_idx = self.get_primary_key_column_index()
                    if primary_key_column_idx is not None:
                        id_item = self.table_view.item(target_row, primary_key_column_idx)
                        if id_item and not id_item.text().endswith('*'):
                            id_item.setText(id_item.text() + ' *')

            self.statusBar.showMessage("Paste successful. Don't forget to save.", 2000)

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
        self.show_errors_action.setChecked(False)
        self.error_label.setText("Click on a red cell to see the error details.")

        if model_name in models.DB_MODELS:
            TableClass = models.DB_MODELS[model_name]
            session = models.DB_SESSION
            engine = session.bind

            headers = [column.key for column in TableClass.__table__.columns]
            self.table_view.setColumnCount(len(headers))
            self.table_view.setHorizontalHeaderLabels(headers)

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
            column_info = {c['name']: c['type'] for c in inspector.get_columns(model_name)}

            self.table_view.setRowCount(len(rows))

            for row_idx, row_tuple in enumerate(rows):
                is_row_invalid = False
                for col_idx, value in enumerate(row_tuple):
                    header = headers[col_idx]
                    column_type = str(column_info.get(header)).upper()

                    value_str = str(value) if value is not None else ""
                    item = QTableWidgetItem(value_str)

                    is_invalid = False
                    if value is not None:
                        try:
                            if "INTEGER" in column_type:
                                int(value)
                            elif "REAL" in column_type or "FLOAT" in column_type:
                                float(value)
                        except (ValueError, TypeError):
                            is_invalid = True
                            is_row_invalid = True

                    if is_invalid:
                        item.setBackground(QColor(255, 100, 100))
                        tooltip_text = f"Data type mismatch! Expected {column_type}, but found a non-numeric value: '{value_str}'."
                        item.setToolTip(tooltip_text)

                    self.table_view.setItem(row_idx, col_idx, item)

                if is_row_invalid:
                    self.error_rows.add(row_idx)

        self.table_view.itemChanged.connect(self.handle_item_changed)

    def toggle_error_filter(self):
        show_errors_only = self.show_errors_action.isChecked()
        for row_idx in range(self.table_view.rowCount()):
            is_error_row = row_idx in self.error_rows
            if show_errors_only:
                self.table_view.setRowHidden(row_idx, not is_error_row)
            else:
                self.table_view.setRowHidden(row_idx, False)

    def display_error_info(self, row, col):
        item = self.table_view.item(row, col)
        if item and item.toolTip():
            self.error_label.setText(item.toolTip())
        else:
            self.error_label.setText("Click on a red cell to see the error details.")

    def handle_item_changed(self, item):
        row = item.row()
        col = item.column()

        self.table_view.itemChanged.disconnect()

        has_error = row in self.error_rows

        if has_error:
            original_value = self.edited_cells.get((row, col), item.text())
            item.setText(original_value)
            QMessageBox.warning(self, "Validation Error",
                                "Cannot edit this row until all data type errors are corrected and saved.")
            self.table_view.itemChanged.connect(self.handle_item_changed)
            return

        if (row, col) not in self.edited_cells:
            original_item = self.table_view.item(row, col)
            original_value = original_item.text() if original_item else ""
            self.edited_cells[(row, col)] = original_value

            self.undo_stack.append({
                "row": row, "col": col,
                "original": original_value,
                "new": item.text()
            })
            self.undo_action.setEnabled(True)
            self.redo_stack.clear()
            self.redo_action.setEnabled(False)

        # NEW: Only color the specific item yellow
        item.setBackground(QColor(255, 255, 150))

        # NEW: Add asterisk to the ID column
        primary_key_column_idx = self.get_primary_key_column_index()
        if primary_key_column_idx is not None:
            id_item = self.table_view.item(row, primary_key_column_idx)
            if id_item and not id_item.text().endswith('*'):
                id_item.setText(id_item.text() + ' *')
                self.edited_rows.add(row)

        self.table_view.itemChanged.connect(self.handle_item_changed)

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
        if not self.edited_cells:
            QMessageBox.information(self, "No Edits", "There are no unsaved changes to commit.")
            return

        if not self.current_table_name:
            QMessageBox.warning(self, "Warning", "Please select a table first.")
            return

        TableClass = models.DB_MODELS[self.current_table_name]
        session = models.DB_SESSION

        try:
            for (row, col), original_value in self.edited_cells.items():
                headers = [column.key for column in TableClass.__table__.columns]
                column_name = headers[col]
                column_obj = TableClass.__table__.columns.get(column_name)

                primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key

                primary_key_item = self.table_view.item(row, headers.index(primary_key_column))
                if not primary_key_item: continue
                primary_key_value = primary_key_item.text().strip(' *')  # NEW: Strip the asterisk

                obj_to_update = session.query(TableClass).filter_by(**{primary_key_column: primary_key_value}).one()

                new_value = self.table_view.item(row, col).text()

                if not new_value and column_obj.nullable:
                    setattr(obj_to_update, column_name, None)
                    continue
                elif not new_value and not column_obj.nullable:
                    QMessageBox.warning(self, "Validation Error", f"Column '{column_name}' cannot be empty.")
                    raise ValueError(f"Non-nullable column '{column_name}' cannot be empty string.")

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
                    QMessageBox.warning(self, "Validation Error",
                                        f"Invalid input for column '{column_name}'. Expected a number, but got '{new_value}'.")
                    raise

                setattr(obj_to_update, column_name, converted_value)

            session.commit()
            QMessageBox.information(self, "Success", f"All edits for '{self.current_table_name}' saved successfully!")

            self.populate_table_view(self.current_table_name)
            self.edited_cells.clear()
            self.undo_stack.clear()
            self.undo_action.setEnabled(False)
            self.redo_stack.clear()
            self.redo_action.setEnabled(False)

        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to save edits: {e}")
            self.populate_table_view(self.current_table_name)

    def delete_selected_rows(self):
        selected_rows = sorted(list(set(item.row() for item in self.table_view.selectedItems())), reverse=True)
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Please select one or more rows to delete.")
            return

        if not self.current_table_name:
            QMessageBox.warning(self, "Warning", "Please select a table first.")
            return

        reply = QMessageBox.question(self, 'Confirm Deletion',
                                     f"Are you sure you want to delete {len(selected_rows)} row(s)?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            TableClass = models.DB_MODELS[self.current_table_name]
            session = models.DB_SESSION
            try:
                for row in selected_rows:
                    headers = [column.key for column in TableClass.__table__.columns]
                    primary_key_column = TableClass.__table__.primary_key.columns.values()[0].key
                    primary_key_item = self.table_view.item(row, headers.index(primary_key_column))
                    if not primary_key_item: continue
                    primary_key_value = primary_key_item.text().strip(' *')  # NEW: Strip the asterisk

                    obj_to_delete = session.query(TableClass).filter_by(**{primary_key_column: primary_key_value}).one()
                    session.delete(obj_to_delete)

                session.commit()
                QMessageBox.information(self, "Success", f"{len(selected_rows)} row(s) deleted successfully!")
                self.populate_table_view(self.current_table_name)
            except Exception as e:
                session.rollback()
                QMessageBox.critical(self, "Error", f"Failed to delete rows: {e}")

    def undo_edit(self):
        if self.undo_stack:
            change = self.undo_stack.pop()
            self.redo_stack.append(change)
            self.redo_action.setEnabled(True)

            row = change["row"]
            col = change["col"]
            original_value = change["original"]

            self.table_view.itemChanged.disconnect()

            item = self.table_view.item(row, col)
            if item:
                item.setText(original_value)
                item.setBackground(QColor(255, 255, 255))  # NEW: Reset background color

            if (row, col) in self.edited_cells:
                del self.edited_cells[(row, col)]

            self.table_view.itemChanged.connect(self.handle_item_changed)

            self.update_row_visuals(row)

        if not self.undo_stack:
            self.undo_action.setEnabled(False)

    def redo_edit(self):
        if self.redo_stack:
            change = self.redo_stack.pop()
            self.undo_stack.append(change)
            self.undo_action.setEnabled(True)

            row = change["row"]
            col = change["col"]
            new_value = change["new"]

            self.table_view.itemChanged.disconnect()

            item = self.table_view.item(row, col)
            if item:
                item.setText(new_value)
                item.setBackground(QColor(255, 255, 150))  # NEW: Restore background color

            self.edited_cells[(row, col)] = change["original"]

            self.table_view.itemChanged.connect(self.handle_item_changed)

            self.update_row_visuals(row)

        if not self.redo_stack:
            self.redo_action.setEnabled(False)

    def update_row_visuals(self, row):
        row_has_edits = any(key[0] == row for key in self.edited_cells.keys())

        primary_key_column_idx = self.get_primary_key_column_index()
        if primary_key_column_idx is not None:
            id_item = self.table_view.item(row, primary_key_column_idx)
            if id_item:
                current_text = id_item.text().strip(' *')
                if row_has_edits:
                    if not id_item.text().endswith('*'):
                        id_item.setText(current_text + ' *')
                else:
                    if id_item.text().endswith('*'):
                        id_item.setText(current_text)

    def show_keybinds_help(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Keybinds")
        msg_box.setText("<h3>Application Hotkeys</h3>")
        msg_box.setInformativeText("""
            <p><b>Ctrl+S:</b> Save all pending edits</p>
            <p><b>Ctrl+R:</b> Refresh the current table view</p>
            <p><b>Ctrl+C:</b> Copy selected cell(s)</p>
            <p><b>Ctrl+V:</b> Paste from clipboard</p>
            <p><b>Ctrl+Z:</b> Undo the last change</p>
            <p><b>Ctrl+Y:</b> Redo the last undone change</p>
            <p><b>Del:</b> Delete selected row(s)</p>
        """)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()